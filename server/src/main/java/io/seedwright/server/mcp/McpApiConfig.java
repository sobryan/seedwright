package io.seedwright.server.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.HttpServletStreamableServerTransportProvider;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Mounts seedwright's product MCP endpoint at {@code /mcp} (Streamable HTTP) — the surface
 * GitHub Copilot CLI and other MCP clients connect to (see docs/integrations/copilot-cli.md).
 */
@Configuration
public class McpApiConfig {

    public static final String MCP_ENDPOINT = "/mcp";

    @Bean
    public McpJsonMapper productMcpJsonMapper(ObjectMapper objectMapper) {
        return new JacksonMcpJsonMapper(objectMapper);
    }

    @Bean
    public HttpServletStreamableServerTransportProvider productMcpTransport(McpJsonMapper mapper) {
        return HttpServletStreamableServerTransportProvider.builder()
                .jsonMapper(mapper)
                .mcpEndpoint(MCP_ENDPOINT)
                .build();
    }

    @Bean
    public ServletRegistrationBean<HttpServletStreamableServerTransportProvider> productMcpServlet(
            HttpServletStreamableServerTransportProvider provider) {
        return new ServletRegistrationBean<>(provider, MCP_ENDPOINT);
    }

    @Bean(destroyMethod = "close")
    public McpSyncServer productMcpServer(HttpServletStreamableServerTransportProvider provider,
                                          ApiTools tools) {
        return McpServer.sync(provider)
                .serverInfo("seedwright", "0.0.1")
                .instructions("seedwright generates reproducible synthetic data. Typical flow: "
                        + "introspect_connection (or hand-write a schema) -> create_blueprint -> "
                        + "generate_dataset -> export_dataset or materialize_dataset (side-"
                        + "effecting; requires the user's explicit confirmation).")
                .capabilities(McpSchema.ServerCapabilities.builder().tools(true).build())
                .tools(tools.specifications())
                .build();
    }
}
