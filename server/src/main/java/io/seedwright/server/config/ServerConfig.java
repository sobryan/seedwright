package io.seedwright.server.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.engine.DataEngine;
import io.seedwright.server.engine.DataEngineProperties;
import io.seedwright.server.engine.McpDataEngine;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ServerConfig {

    /** Real MCP-backed engine; tests register their own {@link DataEngine} bean instead. */
    @Bean(destroyMethod = "close")
    @ConditionalOnMissingBean(DataEngine.class)
    public McpDataEngine dataEngine(DataEngineProperties properties, ObjectMapper objectMapper) {
        return new McpDataEngine(properties, objectMapper);
    }
}
