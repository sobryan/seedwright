package io.seedwright.jdbcmcp;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** DB2 + ANSI dialect behavior (spec FR-M.4 footguns as data, not scattered code). */
class DialectTest {

    @Test
    void resolvesProductNames() {
        assertThat(Dialect.resolve("PostgreSQL")).isEqualTo(Dialect.POSTGRESQL);
        assertThat(Dialect.resolve("H2")).isEqualTo(Dialect.H2);
        assertThat(Dialect.resolve("DB2/LINUXX8664")).isEqualTo(Dialect.DB2);
        assertThat(Dialect.resolve("DB2 for z/OS")).isEqualTo(Dialect.DB2);
        assertThat(Dialect.resolve("Oracle")).isEqualTo(Dialect.ANSI);   // unspecified fallback
        assertThat(Dialect.resolve(null)).isEqualTo(Dialect.ANSI);
    }

    @Test
    void db2TypeMappingsHandleTheFootguns() {
        assertThat(TypeMap.columnType(Dialect.DB2, Map.of("canonical_kind", "BOOLEAN")))
                .isEqualTo("SMALLINT");                       // no native boolean historically
        assertThat(TypeMap.columnType(Dialect.DB2,
                Map.of("canonical_kind", "TIMESTAMP", "tz", true)))
                .isEqualTo("TIMESTAMP");                      // LUW has no tz timestamp
        assertThat(TypeMap.columnType(Dialect.DB2, Map.of("canonical_kind", "STRING")))
                .isEqualTo("CLOB");
        assertThat(TypeMap.columnType(Dialect.DB2,
                Map.of("canonical_kind", "STRING", "length", 50_000)))
                .isEqualTo("CLOB");                           // beyond the 32672 VARCHAR cap
        assertThat(TypeMap.columnType(Dialect.DB2,
                Map.of("canonical_kind", "STRING", "length", 255)))
                .isEqualTo("VARCHAR(255)");
        assertThat(TypeMap.columnType(Dialect.DB2, Map.of("canonical_kind", "BYTES")))
                .isEqualTo("BLOB");
        assertThat(TypeMap.columnType(Dialect.DB2, Map.of("canonical_kind", "UUID")))
                .isEqualTo("CHAR(36)");
        assertThat(TypeMap.columnType(Dialect.DB2,
                Map.of("canonical_kind", "DECIMAL", "precision", 12, "scale", 2)))
                .isEqualTo("NUMERIC(12,2)");                  // money never floats, anywhere
        assertThat(TypeMap.columnType(Dialect.DB2, Map.of("canonical_kind", "FLOAT64")))
                .isEqualTo("DOUBLE");
    }

    @Test
    void postgresKeepsNativeTypes() {
        assertThat(TypeMap.columnType(Dialect.POSTGRESQL, Map.of("canonical_kind", "BOOLEAN")))
                .isEqualTo("BOOLEAN");
        assertThat(TypeMap.columnType(Dialect.POSTGRESQL,
                Map.of("canonical_kind", "TIMESTAMP", "tz", true)))
                .isEqualTo("TIMESTAMP WITH TIME ZONE");
        assertThat(TypeMap.columnType(Dialect.POSTGRESQL, Map.of("canonical_kind", "JSON")))
                .isEqualTo("JSONB");
    }

    @Test
    void bindValuesAdaptBooleanAndTzTimestampPerDialect() throws Exception {
        ObjectMapper json = new ObjectMapper();

        assertThat(BindValues.convert(Dialect.DB2, "BOOLEAN", json.readTree("true")))
                .isEqualTo((short) 1);
        assertThat(BindValues.convert(Dialect.POSTGRESQL, "BOOLEAN", json.readTree("true")))
                .isEqualTo(Boolean.TRUE);

        // tz timestamp on DB2/ANSI: normalized to UTC wall time (LocalDateTime)
        Object db2Value = BindValues.convert(Dialect.DB2, "TIMESTAMP",
                json.readTree("\"2026-07-04T10:00:00+02:00\""));
        assertThat(db2Value).isEqualTo(LocalDateTime.parse("2026-07-04T08:00:00"));
        Object pgValue = BindValues.convert(Dialect.POSTGRESQL, "TIMESTAMP",
                json.readTree("\"2026-07-04T10:00:00+02:00\""));
        assertThat(pgValue).isInstanceOf(OffsetDateTime.class);

        // decimal exactness is dialect-independent
        assertThat(BindValues.convert(Dialect.ANSI, "DECIMAL", json.readTree("\"0.10\"")))
                .isEqualTo(new BigDecimal("0.10"));
    }
}
