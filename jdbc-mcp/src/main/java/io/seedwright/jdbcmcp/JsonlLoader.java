package io.seedwright.jdbcmcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Scoped dataset load/teardown over JDBC (spec FR-G, FR-L), mirroring the proven Python loader's
 * safety model: data lands ONLY in a validated {@code ds_} schema; an ownership marker table
 * ({@code _seedwright}) is written at create and REQUIRED before any drop; the whole load runs in
 * one transaction with a pre-commit row-count verification (FR-F.1c, FR-E.4).
 *
 * <p>Dialect handling is data + two flags ({@link Dialect}): type DDL via {@link TypeMap}, bind
 * values via {@link BindValues}. Teardown and existence checks are PORTABLE by construction —
 * tables are enumerated via JDBC metadata and dropped individually (each schema-qualified into
 * the validated namespace), then {@code DROP SCHEMA <ns> RESTRICT} — because DB2 LUW has no
 * {@code DROP SCHEMA ... CASCADE}, and an unspecified dialect can't be assumed to either.
 *
 * <p>v1 consumes the data-engine's fidelity-preserving JSONL export (+ Load Plan) rather than
 * Parquet directly; direct Parquet reading in Java is a deferred enhancement.
 */
public final class JsonlLoader {

    public static final String MARKER_TABLE = "_seedwright";
    private static final int BATCH_SIZE = 500;

    private final ObjectMapper json = new ObjectMapper();

    public static class ForeignSchemaException extends RuntimeException {
        public ForeignSchemaException(String message) {
            super(message);
        }
    }

    public static class MaterializationException extends RuntimeException {
        public MaterializationException(String message) {
            super(message);
        }
    }

    /** Load every table in the Load Plan from {@code dataDir}/{table}.jsonl. One transaction. */
    public Map<String, Object> loadDataset(Connection conn, Path dataDir,
                                           Map<String, Object> loadPlan, String namespace,
                                           String mode) throws SQLException, IOException {
        SafeSql.validateNamespace(namespace);
        if (!"create".equals(mode) && !"replace".equals(mode)) {
            throw new IllegalArgumentException("mode must be create|replace, got: " + mode);
        }
        Dialect dialect = Dialect.resolve(conn.getMetaData().getDatabaseProductName());
        boolean previousAutoCommit = conn.getAutoCommit();
        conn.setAutoCommit(false);
        try (Statement ddl = conn.createStatement()) {
            boolean exists = schemaExists(conn, namespace);
            if (exists) {
                if ("create".equals(mode)) {
                    throw new IllegalStateException(
                            "schema exists and mode=create: " + namespace);
                }
                requireSeedwrightMarker(conn, namespace);
                dropSchemaScoped(conn, namespace);
            }
            ddl.execute("CREATE SCHEMA " + SafeSql.quoteIdentifier(namespace));
            ddl.execute("CREATE TABLE " + SafeSql.qualified(namespace, MARKER_TABLE)
                    + " (marker VARCHAR(128) NOT NULL)");
            ddl.execute("INSERT INTO " + SafeSql.qualified(namespace, MARKER_TABLE)
                    + " VALUES ('seedwright:" + SafeSql.validateNamespace(namespace) + "')");

            Map<String, Object> tableResults = new LinkedHashMap<>();
            long totalRows = 0;
            for (Map<String, Object> table : tables(loadPlan)) {
                String name = (String) table.get("name");
                List<Map<String, Object>> columns = columns(table);
                ddl.execute(createTableSql(dialect, namespace, name, columns));
                long rows = copyJsonl(conn, dialect, dataDir, namespace, name, columns);
                verifyRowCount(conn, namespace, name, rows);
                tableResults.put(name, rows);
                totalRows += rows;
            }
            conn.commit();
            return Map.of("namespace", namespace, "mode", mode, "dialect", dialect.name(),
                    "total_rows", totalRows, "tables", tableResults);
        } catch (Exception e) {
            conn.rollback();
            throw e;
        } finally {
            conn.setAutoCommit(previousAutoCommit);
        }
    }

    /** Idempotent, marker-guarded teardown: metadata-listed drops, all inside the namespace. */
    public Map<String, Object> teardownDataset(Connection conn, String namespace)
            throws SQLException {
        SafeSql.validateNamespace(namespace);
        boolean exists = schemaExists(conn, namespace);
        if (exists) {
            requireSeedwrightMarker(conn, namespace);
            dropSchemaScoped(conn, namespace);
        }
        return Map.of("namespace", namespace, "existed", exists);
    }

    /** Compare loaded row counts to the Load Plan (post-hoc check; FR-F.1c). */
    public Map<String, Object> verifyMaterialization(Connection conn,
                                                     Map<String, Object> loadPlan,
                                                     String namespace) throws SQLException {
        SafeSql.validateNamespace(namespace);
        List<Map<String, Object>> results = new ArrayList<>();
        boolean ok = true;
        for (Map<String, Object> table : tables(loadPlan)) {
            String name = (String) table.get("name");
            long expected = ((Number) table.get("row_count")).longValue();
            long actual = countRows(conn, namespace, name);
            boolean match = expected == actual;
            ok &= match;
            results.add(Map.of("name", name, "expected_rows", expected,
                    "actual_rows", actual, "ok", match));
        }
        return Map.of("namespace", namespace, "ok", ok, "tables", results);
    }

    // --- internals --------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> tables(Map<String, Object> loadPlan) {
        return (List<Map<String, Object>>) loadPlan.get("tables");
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> columns(Map<String, Object> table) {
        return (List<Map<String, Object>>) table.get("columns");
    }

    private String createTableSql(Dialect dialect, String namespace, String table,
                                  List<Map<String, Object>> columns) {
        StringBuilder sql = new StringBuilder("CREATE TABLE ")
                .append(SafeSql.qualified(namespace, table)).append(" (");
        for (int i = 0; i < columns.size(); i++) {
            Map<String, Object> col = columns.get(i);
            if (i > 0) {
                sql.append(", ");
            }
            sql.append(SafeSql.quoteIdentifier((String) col.get("name")))
                    .append(' ')
                    .append(TypeMap.columnType(dialect, col));
            if (Boolean.FALSE.equals(col.get("nullable"))) {
                sql.append(" NOT NULL");
            }
        }
        return sql.append(')').toString();
    }

    private long copyJsonl(Connection conn, Dialect dialect, Path dataDir, String namespace,
                           String table, List<Map<String, Object>> columns)
            throws SQLException, IOException {
        Path file = resolveJsonl(dataDir, table);
        String placeholders = String.join(", ", java.util.Collections.nCopies(columns.size(), "?"));
        String columnList = columns.stream()
                .map(c -> SafeSql.quoteIdentifier((String) c.get("name")))
                .reduce((a, b) -> a + ", " + b)
                .orElseThrow();
        String insert = "INSERT INTO " + SafeSql.qualified(namespace, table)
                + " (" + columnList + ") VALUES (" + placeholders + ")";

        long rows = 0;
        try (PreparedStatement stmt = conn.prepareStatement(insert);
             BufferedReader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            int pending = 0;
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                JsonNode row = json.readTree(line);
                for (int i = 0; i < columns.size(); i++) {
                    Map<String, Object> col = columns.get(i);
                    stmt.setObject(i + 1, BindValues.convert(
                            dialect, (String) col.get("canonical_kind"),
                            row.get((String) col.get("name"))));
                }
                stmt.addBatch();
                rows++;
                if (++pending >= BATCH_SIZE) {
                    stmt.executeBatch();
                    pending = 0;
                }
            }
            if (pending > 0) {
                stmt.executeBatch();
            }
        }
        return rows;
    }

    /** Table names are untrusted; keep the file resolution inside dataDir (path-segment guard). */
    private Path resolveJsonl(Path dataDir, String table) {
        if (table.contains("/") || table.contains("\\") || table.contains("\0")
                || table.equals(".") || table.equals("..")) {
            throw new SafeSql.UnsafeIdentifierException("unsafe table name: " + table);
        }
        Path path = dataDir.resolve(table + ".jsonl").normalize();
        if (!path.startsWith(dataDir.normalize())) {
            throw new SafeSql.UnsafeIdentifierException("table escapes data dir: " + table);
        }
        return path;
    }

    /**
     * Drop the namespace WITHOUT `DROP SCHEMA ... CASCADE` (DB2 LUW doesn't have it; an
     * unspecified dialect can't be assumed to): enumerate the schema's tables via JDBC metadata,
     * drop each (always schema-qualified into the validated namespace), then drop the schema
     * RESTRICT. Still provably scoped — nothing outside the namespace is ever named.
     */
    private void dropSchemaScoped(Connection conn, String namespace) throws SQLException {
        SafeSql.validateNamespace(namespace);
        List<String> tables = new ArrayList<>();
        try (ResultSet rs = conn.getMetaData().getTables(null, namespace, "%",
                new String[] {"TABLE"})) {
            while (rs.next()) {
                tables.add(rs.getString("TABLE_NAME"));
            }
        }
        try (Statement stmt = conn.createStatement()) {
            for (String table : tables) {
                stmt.execute("DROP TABLE " + SafeSql.qualified(namespace, table));
            }
            stmt.execute("DROP SCHEMA " + SafeSql.quoteIdentifier(namespace) + " RESTRICT");
        }
    }

    private void verifyRowCount(Connection conn, String namespace, String table, long expected)
            throws SQLException {
        long actual = countRows(conn, namespace, table);
        if (actual != expected) {
            throw new MaterializationException(table + ": " + actual
                    + " rows landed but " + expected + " were streamed");
        }
    }

    private long countRows(Connection conn, String namespace, String table) throws SQLException {
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(
                     "SELECT COUNT(*) FROM " + SafeSql.qualified(namespace, table))) {
            rs.next();
            return rs.getLong(1);
        }
    }

    /** Portable existence check via JDBC metadata (DB2 has no information_schema). */
    private boolean schemaExists(Connection conn, String namespace) throws SQLException {
        try (ResultSet rs = conn.getMetaData().getSchemas(null, namespace)) {
            return rs.next();
        }
    }

    private void requireSeedwrightMarker(Connection conn, String namespace) throws SQLException {
        String sql = "SELECT marker FROM " + SafeSql.qualified(namespace, MARKER_TABLE);
        try (Statement stmt = conn.createStatement(); ResultSet rs = stmt.executeQuery(sql)) {
            if (rs.next() && rs.getString(1) != null && rs.getString(1).startsWith("seedwright:")) {
                return;
            }
            throw new ForeignSchemaException(
                    "refusing to drop schema " + namespace + ": marker row missing");
        } catch (SQLException e) {
            throw new ForeignSchemaException(
                    "refusing to drop schema " + namespace + ": not seedwright-marked ("
                            + e.getMessage() + ")");
        }
    }
}
