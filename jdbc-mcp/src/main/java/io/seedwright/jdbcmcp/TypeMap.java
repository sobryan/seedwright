package io.seedwright.jdbcmcp;

import java.util.Map;

/**
 * Canonical kind -> dialect DDL type (spec FR-M.4), keyed by the JDBC product name. The small
 * per-dialect divergences live here as data; adding DB2 later is a new entry, not new code.
 * DECIMAL is always NUMERIC(p,s) — never a float (money must not lose cents).
 */
public final class TypeMap {

    private TypeMap() {}

    private static final Map<String, String> UNBOUNDED_STRING = Map.of(
            "PostgreSQL", "TEXT",
            "H2", "CLOB");

    public static String columnType(String productName, Map<String, Object> columnHint) {
        String kind = (String) columnHint.get("canonical_kind");
        Object precision = columnHint.get("precision");
        Object scale = columnHint.get("scale");
        Object length = columnHint.get("length");
        boolean tz = Boolean.TRUE.equals(columnHint.get("tz"));

        return switch (kind) {
            case "BOOLEAN" -> "BOOLEAN";
            case "INT16" -> "SMALLINT";
            case "INT32" -> "INTEGER";
            case "INT64" -> "BIGINT";
            case "FLOAT32" -> "REAL";
            case "FLOAT64" -> "DOUBLE PRECISION";
            case "DATE" -> "DATE";
            case "TIME" -> "TIME";
            case "TIMESTAMP" -> tz ? "TIMESTAMP WITH TIME ZONE" : "TIMESTAMP";
            case "UUID" -> "UUID";
            case "JSON" -> "PostgreSQL".equals(productName) ? "JSONB"
                    : UNBOUNDED_STRING.getOrDefault(productName, "CLOB");
            case "BYTES" -> "PostgreSQL".equals(productName) ? "BYTEA" : "VARBINARY(1000000)";
            case "DECIMAL" -> precision == null ? "NUMERIC"
                    : scale == null ? "NUMERIC(" + intOf(precision) + ")"
                    : "NUMERIC(" + intOf(precision) + "," + intOf(scale) + ")";
            case "STRING" -> length == null
                    ? UNBOUNDED_STRING.getOrDefault(productName, "CLOB")
                    : "VARCHAR(" + intOf(length) + ")";
            case null, default -> throw new IllegalArgumentException(
                    "unknown canonical kind: " + kind);
        };
    }

    private static int intOf(Object value) {
        if (value instanceof Number n) {
            return n.intValue();
        }
        throw new IllegalArgumentException("expected integer type parameter, got: " + value);
    }
}
