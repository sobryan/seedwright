package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * The scoped JDBC load/teardown against a real (in-memory H2) database — mirrors the Python
 * loader's integration semantics: replace idempotency, marker-guarded drops, decimal exactness,
 * path-safe table names (FR-G, FR-L, FR-M.4).
 */
class JsonlLoaderTest {

    @TempDir
    Path dataDir;

    private Connection conn;
    private final JsonlLoader loader = new JsonlLoader();

    private static final Map<String, Object> LOAD_PLAN = Map.of(
            "namespace", "ds_t",
            "tables", List.of(Map.of(
                    "name", "customers",
                    "row_count", 3,
                    "columns", List.of(
                            Map.of("name", "id", "canonical_kind", "INT64", "nullable", false),
                            Map.of("name", "name", "canonical_kind", "STRING", "length", 255,
                                    "nullable", true),
                            Map.of("name", "balance", "canonical_kind", "DECIMAL",
                                    "precision", 12, "scale", 2, "nullable", false),
                            Map.of("name", "active", "canonical_kind", "BOOLEAN",
                                    "nullable", false)))));

    @BeforeEach
    void setUp() throws Exception {
        conn = DriverManager.getConnection("jdbc:h2:mem:loader;DB_CLOSE_DELAY=-1");
        Files.writeString(dataDir.resolve("customers.jsonl"), """
                {"id": 1, "name": "Ann", "balance": "0.10", "active": true}
                {"id": 2, "name": "O'Brien", "balance": "1000.00", "active": false}
                {"id": 3, "name": null, "balance": "3.99", "active": true}
                """);
    }

    @AfterEach
    void tearDown() throws Exception {
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("DROP ALL OBJECTS");
        }
        conn.close();
    }

    @Test
    void loadsIntoScopedSchemaWithExactDecimals() throws Exception {
        Map<String, Object> result = loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "replace");
        assertThat(result.get("total_rows")).isEqualTo(3L);

        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(
                     "SELECT \"balance\" FROM \"ds_t\".\"customers\" WHERE \"id\" = 1")) {
            rs.next();
            assertThat(rs.getBigDecimal(1)).isEqualByComparingTo(new BigDecimal("0.10"));
            assertThat(rs.getBigDecimal(1).scale()).isEqualTo(2);
        }
        // NULL survived; quote-bearing string survived
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(
                     "SELECT \"name\" FROM \"ds_t\".\"customers\" ORDER BY \"id\"")) {
            rs.next();
            assertThat(rs.getString(1)).isEqualTo("Ann");
            rs.next();
            assertThat(rs.getString(1)).isEqualTo("O'Brien");
            rs.next();
            assertThat(rs.getString(1)).isNull();
        }
    }

    @Test
    void replaceIsIdempotent() throws Exception {
        loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "replace");
        loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "replace");
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM \"ds_t\".\"customers\"")) {
            rs.next();
            assertThat(rs.getLong(1)).isEqualTo(3);
        }
    }

    @Test
    void createModeFailsLoudWhenSchemaExists() throws Exception {
        loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "create");
        assertThatThrownBy(() -> loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "create"))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void teardownIsIdempotentAndScoped() throws Exception {
        assertThat(loader.teardownDataset(conn, "ds_absent").get("existed")).isEqualTo(false);

        loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "replace");
        assertThat(loader.teardownDataset(conn, "ds_t").get("existed")).isEqualTo(true);
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(
                     "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'ds_t'")) {
            assertThat(rs.next()).isFalse();
        }
    }

    @Test
    void refusesToDropForeignUnmarkedSchema() throws Exception {
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("CREATE SCHEMA \"ds_foreign\"");
        }
        assertThatThrownBy(() -> loader.teardownDataset(conn, "ds_foreign"))
                .isInstanceOf(JsonlLoader.ForeignSchemaException.class);
        // and the schema is still there
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(
                     "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'ds_foreign'")) {
            assertThat(rs.next()).isTrue();
        }
    }

    @Test
    void verifyMaterializationComparesCounts() throws Exception {
        loader.loadDataset(conn, dataDir, LOAD_PLAN, "ds_t", "replace");
        Map<String, Object> verification = loader.verifyMaterialization(conn, LOAD_PLAN, "ds_t");
        assertThat(verification.get("ok")).isEqualTo(true);
    }

    @Test
    void pathTraversalTableNameRejected() {
        Map<String, Object> evil = Map.of(
                "namespace", "ds_t",
                "tables", List.of(Map.of(
                        "name", "../evil",
                        "row_count", 0,
                        "columns", List.of(
                                Map.of("name", "id", "canonical_kind", "INT64", "nullable", false)))));
        assertThatThrownBy(() -> loader.loadDataset(conn, dataDir, evil, "ds_t", "replace"))
                .isInstanceOf(SafeSql.UnsafeIdentifierException.class);
    }

    @Test
    void badNamespaceRejectedBeforeAnySql() {
        assertThatThrownBy(() -> loader.loadDataset(conn, dataDir, LOAD_PLAN, "public", "replace"))
                .isInstanceOf(SafeSql.UnsafeNamespaceException.class);
    }
}
