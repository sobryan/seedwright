package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Introspection emits the exact shape the data-engine's author_generator consumes — so
 * "introspect their DB, author a Blueprint" is a straight pipe (FR-A).
 */
class IntrospectorTest {

    private Connection conn;

    @BeforeEach
    void setUp() throws Exception {
        conn = DriverManager.getConnection("jdbc:h2:mem:introspect;DB_CLOSE_DELAY=-1");
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("CREATE TABLE \"customers\" ("
                    + "\"id\" BIGINT PRIMARY KEY, "
                    + "\"email\" VARCHAR(255), "
                    + "\"balance\" NUMERIC(12,2))");
            stmt.execute("CREATE TABLE \"orders\" ("
                    + "\"id\" BIGINT PRIMARY KEY, "
                    + "\"customer_id\" BIGINT REFERENCES \"customers\"(\"id\"), "
                    + "\"total\" NUMERIC(10,2))");
        }
    }

    @AfterEach
    void tearDown() throws Exception {
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("DROP ALL OBJECTS");
        }
        conn.close();
    }

    @Test
    @SuppressWarnings("unchecked")
    void introspectsTablesColumnsPrimaryKeysAndForeignKeys() throws Exception {
        Map<String, Object> result = Introspector.introspect(conn, "PUBLIC");

        Map<String, Object> schema = (Map<String, Object>) result.get("schema");
        assertThat(schema).containsKeys("customers", "orders");

        Map<String, Object> customers = (Map<String, Object>) schema.get("customers");
        List<Map<String, Object>> columns = (List<Map<String, Object>>) customers.get("columns");
        assertThat(columns).extracting(c -> c.get("name"))
                .containsExactly("id", "email", "balance");
        assertThat(columns).extracting(c -> c.get("sql_type"))
                .containsExactly("bigint", "varchar(255)", "numeric(12,2)");
        assertThat((List<String>) customers.get("primary_key")).containsExactly("id");

        Map<String, Object> fks = (Map<String, Object>) result.get("foreign_keys");
        List<Map<String, Object>> orderFks = (List<Map<String, Object>>) fks.get("orders");
        assertThat(orderFks).hasSize(1);
        assertThat(orderFks.get(0))
                .containsEntry("column", "customer_id")
                .containsEntry("references_table", "customers")
                .containsEntry("references_column", "id");
    }
}
