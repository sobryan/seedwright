package io.seedwright.jdbcmcp;

/**
 * The dialects this node knows natively, resolved from the JDBC product name. Anything
 * unrecognized falls back to {@link #ANSI} — conservative type mappings + the portable
 * teardown — so an unspecified database works by just dropping its driver jar into the
 * drivers directory and using its JDBC URL.
 */
public enum Dialect {
    POSTGRESQL,
    H2,
    DB2,
    ANSI;

    public static Dialect resolve(String jdbcProductName) {
        if (jdbcProductName == null) {
            return ANSI;
        }
        String name = jdbcProductName.toLowerCase();
        if (name.contains("postgresql")) {
            return POSTGRESQL;
        }
        if (name.startsWith("h2")) {
            return H2;
        }
        if (name.startsWith("db2")) {
            return DB2;
        }
        return ANSI;
    }

    /** DB2 LUW (and the conservative ANSI fallback) have no native BOOLEAN column type. */
    public boolean booleanAsSmallint() {
        return this == DB2 || this == ANSI;
    }

    /** DB2 LUW (and the ANSI fallback) have no TIMESTAMP WITH TIME ZONE — store UTC wall time. */
    public boolean timestampTzUnsupported() {
        return this == DB2 || this == ANSI;
    }
}
