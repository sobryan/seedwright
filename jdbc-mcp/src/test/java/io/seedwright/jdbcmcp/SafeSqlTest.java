package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** Mirrors the Python loader's safesql tests — the injection keystone (FR-L). */
class SafeSqlTest {

    @ParameterizedTest
    @ValueSource(strings = {"ds_1", "ds_abc123", "ds_a_b_c"})
    void validNamespacesAccepted(String ns) {
        assertThat(SafeSql.validateNamespace(ns)).isEqualTo(ns);
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "customers", "public", "pg_catalog", "information_schema",
        "ds_ABC", "ds_", "ds_a-b", "ds_a\"; DROP SCHEMA public CASCADE;--", ""
    })
    void invalidNamespacesRejected(String ns) {
        assertThatThrownBy(() -> SafeSql.validateNamespace(ns))
                .isInstanceOf(SafeSql.UnsafeNamespaceException.class);
    }

    @Test
    void namespaceOver63BytesRejected() {
        assertThat(SafeSql.validateNamespace("ds_" + "a".repeat(60))).isNotNull();
        assertThatThrownBy(() -> SafeSql.validateNamespace("ds_" + "a".repeat(61)))
                .isInstanceOf(SafeSql.UnsafeNamespaceException.class);
    }

    @Test
    void identifierNeutralizesInjection() {
        assertThat(SafeSql.quoteIdentifier("x\"; DROP TABLE users; --"))
                .isEqualTo("\"x\"\"; DROP TABLE users; --\"");
    }

    @Test
    void identifierRejectsEmptyAndNul() {
        assertThatThrownBy(() -> SafeSql.quoteIdentifier(""))
                .isInstanceOf(SafeSql.UnsafeIdentifierException.class);
        assertThatThrownBy(() -> SafeSql.quoteIdentifier("a\0b"))
                .isInstanceOf(SafeSql.UnsafeIdentifierException.class);
    }

    @Test
    void qualifiedValidatesBothParts() {
        assertThat(SafeSql.qualified("ds_1", "orders")).isEqualTo("\"ds_1\".\"orders\"");
        assertThatThrownBy(() -> SafeSql.qualified("public", "orders"))
                .isInstanceOf(SafeSql.UnsafeNamespaceException.class);
    }
}
