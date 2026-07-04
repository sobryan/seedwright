package io.seedwright.jdbcmcp;

import java.util.Map;

/**
 * Canonical kind -> dialect DDL type (spec FR-M.4). The per-dialect divergences live here as
 * data; adding a dialect is a new column, not new code. DECIMAL is always NUMERIC(p,s) — never
 * a float (money must not lose cents).
 *
 * <p>DB2 LUW footguns handled: no native BOOLEAN historically (SMALLINT 0/1), VARCHAR caps at
 * 32672 bytes (CLOB beyond), no TIMESTAMP WITH TIME ZONE (UTC wall time in TIMESTAMP; the
 * binder normalizes offsets to UTC). The ANSI fallback uses the same conservative choices so an
 * unspecified dialect has the best odds of just working.
 */
public final class TypeMap {

    private TypeMap() {}

    private static final int DB2_VARCHAR_MAX = 32_672;

    public static String columnType(Dialect dialect, Map<String, Object> columnHint) {
        String kind = (String) columnHint.get("canonical_kind");
        Object precision = columnHint.get("precision");
        Object scale = columnHint.get("scale");
        Object length = columnHint.get("length");
        boolean tz = Boolean.TRUE.equals(columnHint.get("tz"));

        return switch (kind) {
            case "BOOLEAN" -> dialect.booleanAsSmallint() ? "SMALLINT" : "BOOLEAN";
            case "INT16" -> "SMALLINT";
            case "INT32" -> "INTEGER";
            case "INT64" -> "BIGINT";
            case "FLOAT32" -> "REAL";
            case "FLOAT64" -> dialect == Dialect.DB2 ? "DOUBLE" : "DOUBLE PRECISION";
            case "DATE" -> "DATE";
            case "TIME" -> "TIME";
            case "TIMESTAMP" -> tz && !dialect.timestampTzUnsupported()
                    ? "TIMESTAMP WITH TIME ZONE" : "TIMESTAMP";
            case "UUID" -> dialect == Dialect.POSTGRESQL || dialect == Dialect.H2
                    ? "UUID" : "CHAR(36)";
            case "JSON" -> switch (dialect) {
                case POSTGRESQL -> "JSONB";
                case H2, DB2, ANSI -> "CLOB";
            };
            case "BYTES" -> switch (dialect) {
                case POSTGRESQL -> "BYTEA";
                case H2 -> "VARBINARY(1000000)";
                case DB2, ANSI -> "BLOB";
            };
            case "DECIMAL" -> precision == null ? "NUMERIC"
                    : scale == null ? "NUMERIC(" + intOf(precision) + ")"
                    : "NUMERIC(" + intOf(precision) + "," + intOf(scale) + ")";
            case "STRING" -> stringType(dialect, length);
            case null, default -> throw new IllegalArgumentException(
                    "unknown canonical kind: " + kind);
        };
    }

    private static String stringType(Dialect dialect, Object length) {
        if (length != null) {
            int n = intOf(length);
            if ((dialect == Dialect.DB2 || dialect == Dialect.ANSI) && n > DB2_VARCHAR_MAX) {
                return "CLOB";
            }
            return "VARCHAR(" + n + ")";
        }
        return switch (dialect) {
            case POSTGRESQL -> "TEXT";
            case H2, DB2, ANSI -> "CLOB";
        };
    }

    private static int intOf(Object value) {
        if (value instanceof Number n) {
            return n.intValue();
        }
        throw new IllegalArgumentException("expected integer type parameter, got: " + value);
    }
}
