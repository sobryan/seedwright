package io.seedwright.jdbcmcp;

import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Identifier + namespace safety — the injection keystone, mirroring the proven Python loader's
 * {@code safesql} module (FR-L). Imported table/column names are untrusted; every piece of DDL
 * and DML composes identifiers through here. The mandatory {@code ds_} prefix makes a namespace
 * structurally collision-proof with real application schemas, so a scoped schema drop can never
 * hit one (FR-L.3).
 */
public final class SafeSql {

    public static final String NAMESPACE_PREFIX = "ds_";
    public static final int MAX_IDENTIFIER_BYTES = 63;

    private static final Pattern NAMESPACE = Pattern.compile("^ds_[a-z0-9_]+$");
    private static final Set<String> RESERVED =
            Set.of("public", "pg_catalog", "information_schema", "pg_toast");

    private SafeSql() {}

    public static class UnsafeNamespaceException extends IllegalArgumentException {
        public UnsafeNamespaceException(String message) {
            super(message);
        }
    }

    public static class UnsafeIdentifierException extends IllegalArgumentException {
        public UnsafeIdentifierException(String message) {
            super(message);
        }
    }

    /** Validate a Dataset namespace: mandatory ds_ prefix, lowercase, bounded, not reserved. */
    public static String validateNamespace(String namespace) {
        if (namespace == null || RESERVED.contains(namespace) || namespace.startsWith("pg_")) {
            throw new UnsafeNamespaceException("reserved or null namespace: " + namespace);
        }
        if (!NAMESPACE.matcher(namespace).matches()) {
            throw new UnsafeNamespaceException(
                    "namespace must match ^ds_[a-z0-9_]+$ : " + namespace);
        }
        if (namespace.getBytes(StandardCharsets.UTF_8).length > MAX_IDENTIFIER_BYTES) {
            throw new UnsafeNamespaceException("namespace exceeds 63 bytes: " + namespace);
        }
        return namespace;
    }

    /** Double-quote an identifier, doubling embedded quotes; reject what quoting can't fix. */
    public static String quoteIdentifier(String name) {
        if (name == null || name.isEmpty()) {
            throw new UnsafeIdentifierException("empty identifier");
        }
        if (name.indexOf('\0') >= 0) {
            throw new UnsafeIdentifierException("identifier contains NUL");
        }
        if (name.getBytes(StandardCharsets.UTF_8).length > MAX_IDENTIFIER_BYTES) {
            throw new UnsafeIdentifierException("identifier too long: " + name);
        }
        return '"' + name.replace("\"", "\"\"") + '"';
    }

    /** {@code "namespace"."table"} with both parts validated. */
    public static String qualified(String namespace, String table) {
        return quoteIdentifier(validateNamespace(namespace)) + "." + quoteIdentifier(table);
    }
}
