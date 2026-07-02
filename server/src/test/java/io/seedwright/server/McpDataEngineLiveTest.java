package io.seedwright.server;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.engine.DataEngineProperties;
import io.seedwright.server.engine.McpDataEngine;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * LIVE Java <-> Python seam test: spawn the real data-engine over stdio MCP and author a
 * generator. Skipped when `uv` or the data-engine project isn't present (CI without Python).
 * This is the cross-language contract test for ADR-0004.
 */
class McpDataEngineLiveTest {

    private static final Path DATA_ENGINE = Path.of("..", "data-engine").toAbsolutePath().normalize();

    private static boolean uvAvailable() {
        try {
            Process process = new ProcessBuilder("uv", "--version").start();
            return process.waitFor() == 0;
        } catch (Exception e) {
            return false;
        }
    }

    @Test
    void authorsAGeneratorOverRealStdioMcp() throws Exception {
        assumeTrue(Files.isDirectory(DATA_ENGINE), "data-engine project not found");
        assumeTrue(uvAvailable(), "uv not available");

        DataEngineProperties properties = new DataEngineProperties(
                "uv",
                List.of("run", "--project", DATA_ENGINE.toString(), "seedwright-data-engine"),
                Duration.ofMinutes(2));
        try (McpDataEngine engine = new McpDataEngine(properties, new ObjectMapper())) {
            Map<String, Object> artifacts = engine.authorGenerator(
                    Map.of("customers", Map.of(
                            "columns", List.of(
                                    Map.of("name", "id", "sql_type", "bigint"),
                                    Map.of("name", "email", "sql_type", "varchar(255)")),
                            "primary_key", List.of("id"))),
                    List.of(),
                    null,
                    Map.of("customers", 10),
                    7L,
                    "heuristic");

            assertThat((String) artifacts.get("version")).startsWith("ga_");
            Map<?, ?> provenance = (Map<?, ?>) artifacts.get("provenance");
            assertThat(provenance.get("provider_id")).isEqualTo("heuristic");
            assertThat(provenance.get("determinism_gate_passed")).isEqualTo(true);
            assertThat(provenance.get("approval_status")).isEqualTo("pending_approval");
        }
    }
}
