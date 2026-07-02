package io.seedwright.server.engine;

import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** How the central server spawns and talks to the Python MCP data-engine (stdio). */
@ConfigurationProperties(prefix = "seedwright.data-engine")
public record DataEngineProperties(String command, List<String> args, Duration requestTimeout) {

    public DataEngineProperties {
        if (command == null || command.isBlank()) {
            command = "uv";
        }
        if (args == null || args.isEmpty()) {
            args = List.of("run", "--project", "../data-engine", "seedwright-data-engine");
        }
        if (requestTimeout == null) {
            requestTimeout = Duration.ofMinutes(30);
        }
    }
}
