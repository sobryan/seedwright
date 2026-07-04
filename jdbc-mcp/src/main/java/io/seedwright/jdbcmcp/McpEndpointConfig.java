package io.seedwright.jdbcmcp;

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

/** Mounts the MCP server (Streamable HTTP) at {@code /mcp} inside embedded Tomcat. */
@Configuration
public class McpEndpointConfig {

    public static final String MCP_ENDPOINT = "/mcp";

    /** Drop-in JDBC driver jars for unspecified dialects (DB2 jcc, Oracle ojdbc, ...). */
    @Bean
    public DriverDirectoryLoader driverDirectoryLoader(
            @org.springframework.beans.factory.annotation.Value(
                    "${seedwright.driver-dir:./drivers}") String driverDir) {
        return new DriverDirectoryLoader(java.nio.file.Path.of(driverDir));
    }

    @Bean
    public McpJsonMapper mcpJsonMapper(ObjectMapper objectMapper) {
        return new JacksonMcpJsonMapper(objectMapper);
    }

    @Bean
    public HttpServletStreamableServerTransportProvider transportProvider(McpJsonMapper mapper) {
        return HttpServletStreamableServerTransportProvider.builder()
                .jsonMapper(mapper)
                .mcpEndpoint(MCP_ENDPOINT)
                .build();
    }

    @Bean
    public ServletRegistrationBean<HttpServletStreamableServerTransportProvider> mcpServlet(
            HttpServletStreamableServerTransportProvider provider) {
        return new ServletRegistrationBean<>(provider, MCP_ENDPOINT);
    }

    @Bean(destroyMethod = "close")
    public McpSyncServer mcpServer(HttpServletStreamableServerTransportProvider provider,
                                   JdbcTools tools) {
        return McpServer.sync(provider)
                .serverInfo("seedwright-jdbc-mcp", "0.0.1")
                .capabilities(McpSchema.ServerCapabilities.builder().tools(true).build())
                .tools(tools.specifications())
                .build();
    }
}
