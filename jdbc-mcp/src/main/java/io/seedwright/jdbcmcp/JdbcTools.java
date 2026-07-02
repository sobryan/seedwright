package io.seedwright.jdbcmcp;

import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * The normalized loader contract as MCP tools (spec §7): introspect_schema, load_dataset,
 * teardown_dataset, verify_materialization. Tool handlers delegate to the tested
 * {@link Introspector} / {@link JsonlLoader}; domain failures come back as isError tool results
 * (never protocol faults) so the orchestrator can branch deterministically.
 */
@Component
public class JdbcTools {

    private static final Logger log = LoggerFactory.getLogger(JdbcTools.class);

    private final ConnectionRegistry connections;
    private final JsonlLoader loader = new JsonlLoader();

    public JdbcTools(ConnectionRegistry connections) {
        this.connections = connections;
    }

    public List<SyncToolSpecification> specifications() {
        return List.of(
                spec("introspect_schema",
                        "Introspect tables/columns/PKs/FKs of a named connection's schema",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "connection", Map.of("type", "string"),
                                        "schema", Map.of("type", "string")),
                                "required", List.of("connection")),
                        args -> withConnection(args, conn ->
                                Introspector.introspect(conn, (String) args.get("schema")))),
                spec("load_dataset",
                        "Load a dataset (JSONL export + Load Plan) into a scoped ds_ schema",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "connection", Map.of("type", "string"),
                                        "data_dir", Map.of("type", "string"),
                                        "load_plan", Map.of("type", "object"),
                                        "namespace", Map.of("type", "string"),
                                        "mode", Map.of("type", "string")),
                                "required", List.of("connection", "data_dir", "load_plan", "namespace")),
                        args -> withConnection(args, conn -> loader.loadDataset(
                                conn,
                                Path.of((String) args.get("data_dir")),
                                asMap(args.get("load_plan")),
                                (String) args.get("namespace"),
                                args.getOrDefault("mode", "replace").toString()))),
                spec("teardown_dataset",
                        "Drop a dataset's ds_ schema (idempotent, marker-guarded)",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "connection", Map.of("type", "string"),
                                        "namespace", Map.of("type", "string")),
                                "required", List.of("connection", "namespace")),
                        args -> withConnection(args, conn ->
                                loader.teardownDataset(conn, (String) args.get("namespace")))),
                spec("verify_materialization",
                        "Compare loaded row counts to the Load Plan",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "connection", Map.of("type", "string"),
                                        "load_plan", Map.of("type", "object"),
                                        "namespace", Map.of("type", "string")),
                                "required", List.of("connection", "load_plan", "namespace")),
                        args -> withConnection(args, conn -> loader.verifyMaterialization(
                                conn, asMap(args.get("load_plan")), (String) args.get("namespace")))));
    }

    @FunctionalInterface
    interface JdbcAction {
        Object apply(Connection conn) throws Exception;
    }

    private Object withConnection(Map<String, Object> args, JdbcAction action) throws Exception {
        String name = (String) args.get("connection");
        try (Connection conn = connections.open(name)) {
            return action.apply(conn);
        }
    }

    @FunctionalInterface
    interface ToolHandler {
        Object handle(Map<String, Object> args) throws Exception;
    }

    private SyncToolSpecification spec(String name, String description,
                                       Map<String, Object> inputSchema, ToolHandler handler) {
        return SyncToolSpecification.builder()
                .tool(McpSchema.Tool.builder()
                        .name(name)
                        .description(description)
                        .inputSchema(inputSchema)
                        .build())
                .callHandler((exchange, request) -> {
                    try {
                        Object result = handler.handle(request.arguments());
                        return CallToolResult.builder().structuredContent(result).build();
                    } catch (Exception e) {
                        log.warn("tool {} failed", name, e);
                        return CallToolResult.builder()
                                .isError(true)
                                .content(List.of(new McpSchema.TextContent(
                                        e.getClass().getSimpleName() + ": " + e.getMessage())))
                                .build();
                    }
                })
                .build();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        return (Map<String, Object>) value;
    }
}
