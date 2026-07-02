package io.seedwright.server.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.engine.DataEngine;
import io.seedwright.server.engine.DataEngineProperties;
import io.seedwright.server.engine.McpDataEngine;
import io.seedwright.server.loader.LoaderClient;
import io.seedwright.server.loader.McpLoaderClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(McpLoaderClient.LoaderProperties.class)
public class ServerConfig {

    /** Real MCP-backed engine; tests register their own {@link DataEngine} bean instead. */
    @Bean(destroyMethod = "close")
    @ConditionalOnMissingBean(DataEngine.class)
    public McpDataEngine dataEngine(DataEngineProperties properties, ObjectMapper objectMapper) {
        return new McpDataEngine(properties, objectMapper);
    }

    /** Real MCP client to the jdbc-mcp node; tests register their own {@link LoaderClient}. */
    @Bean(destroyMethod = "close")
    @ConditionalOnMissingBean(LoaderClient.class)
    public McpLoaderClient loaderClient(McpLoaderClient.LoaderProperties properties,
                                        ObjectMapper objectMapper) {
        return new McpLoaderClient(properties, objectMapper);
    }
}
