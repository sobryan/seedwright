package io.seedwright.jdbcmcp;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Schema introspection over JDBC metadata (spec FR-A). Emits exactly the shape the data-engine's
 * {@code author_generator} tool consumes — {@code schema} (columns + primary_key per table) and
 * {@code foreign_keys} — so introspect feeds Blueprint creation directly.
 */
public final class Introspector {

    private Introspector() {}

    public static Map<String, Object> introspect(Connection connection, String schemaPattern)
            throws SQLException {
        DatabaseMetaData meta = connection.getMetaData();
        Map<String, Object> tables = new LinkedHashMap<>();
        Map<String, Object> foreignKeys = new LinkedHashMap<>();

        try (ResultSet rs = meta.getTables(null, schemaPattern, "%", new String[] {"TABLE"})) {
            while (rs.next()) {
                String schema = rs.getString("TABLE_SCHEM");
                String table = rs.getString("TABLE_NAME");

                List<Map<String, Object>> columns = new ArrayList<>();
                try (ResultSet cols = meta.getColumns(null, schema, table, "%")) {
                    while (cols.next()) {
                        columns.add(Map.of(
                                "name", cols.getString("COLUMN_NAME"),
                                "sql_type", renderSqlType(cols)));
                    }
                }

                List<String> primaryKey = new ArrayList<>();
                try (ResultSet pks = meta.getPrimaryKeys(null, schema, table)) {
                    while (pks.next()) {
                        primaryKey.add(pks.getString("COLUMN_NAME"));
                    }
                }

                List<Map<String, Object>> fks = new ArrayList<>();
                try (ResultSet imported = meta.getImportedKeys(null, schema, table)) {
                    while (imported.next()) {
                        fks.add(Map.of(
                                "column", imported.getString("FKCOLUMN_NAME"),
                                "references_table", imported.getString("PKTABLE_NAME"),
                                "references_column", imported.getString("PKCOLUMN_NAME")));
                    }
                }

                tables.put(table, Map.of("columns", columns, "primary_key", primaryKey));
                if (!fks.isEmpty()) {
                    foreignKeys.put(table, fks);
                }
            }
        }
        return Map.of("schema", tables, "foreign_keys", foreignKeys);
    }

    /** Render a SQL type string the canonical parser understands (genlib from_sql vocabulary). */
    private static String renderSqlType(ResultSet cols) throws SQLException {
        int jdbcType = cols.getInt("DATA_TYPE");
        int size = cols.getInt("COLUMN_SIZE");
        int digits = cols.getInt("DECIMAL_DIGITS");

        return switch (jdbcType) {
            case Types.BOOLEAN, Types.BIT -> "boolean";
            case Types.SMALLINT, Types.TINYINT -> "smallint";
            case Types.INTEGER -> "integer";
            case Types.BIGINT -> "bigint";
            case Types.REAL -> "real";
            case Types.FLOAT, Types.DOUBLE -> "double precision";
            case Types.NUMERIC, Types.DECIMAL -> "numeric(" + size + "," + Math.max(digits, 0) + ")";
            case Types.CHAR, Types.NCHAR -> "char(" + size + ")";
            case Types.VARCHAR, Types.NVARCHAR, Types.LONGVARCHAR -> size > 0 && size < 1_000_000
                    ? "varchar(" + size + ")" : "text";
            case Types.CLOB, Types.NCLOB -> "text";
            case Types.DATE -> "date";
            case Types.TIME -> "time";
            case Types.TIME_WITH_TIMEZONE -> "time with time zone";
            case Types.TIMESTAMP -> "timestamp";
            case Types.TIMESTAMP_WITH_TIMEZONE -> "timestamp with time zone";
            case Types.BINARY, Types.VARBINARY, Types.LONGVARBINARY, Types.BLOB -> "bytea";
            case Types.OTHER -> otherType(cols);
            default -> "text"; // permissive fallback; validation catches unsupported kinds later
        };
    }

    private static String otherType(ResultSet cols) throws SQLException {
        String typeName = cols.getString("TYPE_NAME");
        if (typeName == null) {
            return "text";
        }
        return switch (typeName.toLowerCase()) {
            case "uuid" -> "uuid";
            case "jsonb", "json" -> typeName.toLowerCase();
            default -> "text";
        };
    }
}
