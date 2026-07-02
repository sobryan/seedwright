package io.seedwright.server.loader;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * MCP client to the jdbc-mcp node over Streamable HTTP ("server dials into node", ADR-0004).
 * On-prem the node listens on localhost; the same client later points at a remote relay node.
 */
public class McpLoaderClient implements LoaderClient, AutoCloseable {

    @ConfigurationProperties(prefix = "seedwright.jdbc-mcp")
    public record LoaderProperties(String url, Duration requestTimeout) {
        public LoaderProperties {
            if (url == null || url.isBlank()) {
                url = "http://127.0.0.1:8081";
            }
            if (requestTimeout == null) {
                requestTimeout = Duration.ofMinutes(30);
            }
        }
    }

    private final LoaderProperties properties;
    private final ObjectMapper objectMapper;
    private McpSyncClient client;

    public McpLoaderClient(LoaderProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    @Override
    @SuppressWarnings("unchecked")
    public List<String> listConnections() {
        return (List<String>) call("list_connections", Map.of()).get("connections");
    }

    @Override
    public Map<String, Object> introspectSchema(String connection, String schemaPattern) {
        Map<String, Object> args = new HashMap<>();
        args.put("connection", connection);
        if (schemaPattern != null) {
            args.put("schema", schemaPattern);
        }
        return call("introspect_schema", args);
    }

    @Override
    public Map<String, Object> loadDataset(String connection, String dataDir,
                                           Map<String, Object> loadPlan, String namespace,
                                           String mode) {
        return call("load_dataset", Map.of(
                "connection", connection,
                "data_dir", dataDir,
                "load_plan", loadPlan,
                "namespace", namespace,
                "mode", mode));
    }

    @Override
    public Map<String, Object> teardownDataset(String connection, String namespace) {
        return call("teardown_dataset", Map.of("connection", connection, "namespace", namespace));
    }

    @Override
    public Map<String, Object> verifyMaterialization(String connection,
                                                     Map<String, Object> loadPlan,
                                                     String namespace) {
        return call("verify_materialization", Map.of(
                "connection", connection, "load_plan", loadPlan, "namespace", namespace));
    }

    @SuppressWarnings("unchecked")
    private synchronized Map<String, Object> call(String tool, Map<String, Object> args) {
        CallToolResult result = ensureClient().callTool(new CallToolRequest(tool, args));
        if (Boolean.TRUE.equals(result.isError())) {
            throw new LoaderException(tool + " failed: " + summarize(result));
        }
        Object structured = result.structuredContent();
        if (structured instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        throw new LoaderException(tool + " returned no structured content");
    }

    private String summarize(CallToolResult result) {
        try {
            return objectMapper.writeValueAsString(result.content());
        } catch (Exception e) {
            return String.valueOf(result.content());
        }
    }

    private McpSyncClient ensureClient() {
        if (client == null) {
            var transport = HttpClientStreamableHttpTransport.builder(properties.url())
                    .endpoint("/mcp")
                    .jsonMapper(new JacksonMcpJsonMapper(objectMapper))
                    .build();
            client = McpClient.sync(transport)
                    .requestTimeout(properties.requestTimeout())
                    .build();
            client.initialize();
        }
        return client;
    }

    @Override
    public synchronized void close() {
        if (client != null) {
            client.closeGracefully();
            client = null;
        }
    }

    public static class LoaderException extends RuntimeException {
        public LoaderException(String message) {
            super(message);
        }
    }
}
