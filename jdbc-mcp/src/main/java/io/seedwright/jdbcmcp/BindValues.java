package io.seedwright.jdbcmcp;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeParseException;
import java.util.HexFormat;

/**
 * JSONL value -> JDBC bind object, per canonical kind and dialect (spec FR-M.4 fidelity):
 * decimals bind via {@link BigDecimal} from their exact string form (never float); booleans
 * become {@code 1/0} shorts where the dialect maps BOOLEAN to SMALLINT (DB2/ANSI); tz-aware
 * timestamps are normalized to UTC wall time where the dialect has no tz type.
 */
public final class BindValues {

    private BindValues() {}

    public static Object convert(Dialect dialect, String kind, JsonNode value) {
        if (value == null || value.isNull()) {
            return null;
        }
        return switch (kind) {
            case "INT16", "INT32", "INT64" -> value.asLong();
            case "FLOAT32", "FLOAT64" -> value.asDouble();
            case "DECIMAL" -> new BigDecimal(value.asText());
            case "BOOLEAN" -> dialect.booleanAsSmallint()
                    ? (short) (value.asBoolean() ? 1 : 0)
                    : value.asBoolean();
            case "DATE" -> LocalDate.parse(value.asText());
            case "TIME" -> LocalTime.parse(value.asText());
            case "TIMESTAMP" -> timestamp(dialect, value.asText());
            case "BYTES" -> HexFormat.of().parseHex(value.asText());
            case null, default -> value.asText(); // STRING, UUID, JSON
        };
    }

    private static Object timestamp(Dialect dialect, String text) {
        String normalized = text.replace(' ', 'T');
        try {
            OffsetDateTime aware = OffsetDateTime.parse(normalized);
            if (dialect.timestampTzUnsupported()) {
                // no tz column type: store UTC wall time deterministically
                return aware.withOffsetSameInstant(ZoneOffset.UTC).toLocalDateTime();
            }
            return aware;
        } catch (DateTimeParseException e) {
            return LocalDateTime.parse(normalized);
        }
    }
}
