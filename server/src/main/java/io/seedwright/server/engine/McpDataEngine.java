package io.seedwright.server.engine;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.ServerParameters;
import io.modelcontextprotocol.client.transport.StdioClientTransport;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP client to the Python data-engine over stdio (ADR-0004). The engine process is spawned
 * lazily on first use and re-spawned if a call finds it dead. Calls are serialized: one engine
 * process, one in-flight tool call (the JobManager's semaphore bounds real concurrency anyway;
 * per-job engine processes are a later scale-out).
 */
public class McpDataEngine implements DataEngine, AutoCloseable {

    private final DataEngineProperties properties;
    private final ObjectMapper objectMapper;
    private McpSyncClient client;

    public McpDataEngine(DataEngineProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    @Override
    public Map<String, Object> authorGenerator(Map<String, Object> schema,
                                               List<Map<String, Object>> rules,
                                               Map<String, Object> foreignKeys,
                                               Map<String, Object> volumes,
                                               long seed) {
        Map<String, Object> args = new HashMap<>();
        args.put("schema", schema);
        args.put("rules", rules == null ? List.of() : rules);
        if (foreignKeys != null) {
            args.put("foreign_keys", foreignKeys);
        }
        if (volumes != null) {
            args.put("volumes", volumes);
        }
        args.put("seed", seed);
        return call("author_generator", args);
    }

    @Override
    public Map<String, Object> generateDataset(Map<String, Object> artifacts,
                                               Map<String, Object> schema,
                                               String outDir,
                                               String namespace) {
        return call("generate_dataset", Map.of(
                "artifacts", artifacts,
                "schema", schema,
                "out_dir", outDir,
                "namespace", namespace));
    }

    @Override
    public Map<String, Object> validateDataset(String canonicalDir,
                                               Map<String, Object> loadPlan,
                                               List<Map<String, Object>> dataTests) {
        return call("validate_dataset", Map.of(
                "canonical_dir", canonicalDir,
                "load_plan", loadPlan,
                "data_tests", dataTests));
    }

    @Override
    public Map<String, Object> exportDataset(String canonicalDir,
                                             Map<String, Object> loadPlan,
                                             String outDir,
                                             List<String> formats) {
        return call("export_dataset", Map.of(
                "canonical_dir", canonicalDir,
                "load_plan", loadPlan,
                "out_dir", outDir,
                "formats", formats));
    }

    @SuppressWarnings("unchecked")
    private synchronized Map<String, Object> call(String tool, Map<String, Object> args) {
        CallToolResult result = ensureClient().callTool(new CallToolRequest(tool, args));
        if (Boolean.TRUE.equals(result.isError())) {
            throw new DataEngineException(tool + " failed: " + summarize(result));
        }
        Object structured = result.structuredContent();
        if (structured instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        throw new DataEngineException(tool + " returned no structured content");
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
            ServerParameters params = ServerParameters.builder(properties.command())
                    .args(properties.args())
                    .build();
            StdioClientTransport transport =
                    new StdioClientTransport(params, new JacksonMcpJsonMapper(objectMapper));
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

    public static class DataEngineException extends RuntimeException {
        public DataEngineException(String message) {
            super(message);
        }
    }
}
