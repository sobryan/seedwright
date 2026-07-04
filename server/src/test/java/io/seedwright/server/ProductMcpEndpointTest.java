package io.seedwright.server;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.seedwright.server.engine.DataEngine;
import io.seedwright.server.loader.LoaderClient;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/**
 * The integration surface GitHub Copilot CLI uses: a REAL MCP client (the SDK's Streamable HTTP
 * transport) drives the full product flow through /mcp — exactly what an agent does.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "spring.datasource.url=jdbc:h2:mem:mcptest;DB_CLOSE_DELAY=-1",
            "seedwright.work-dir=${java.io.tmpdir}/seedwright-mcp-work",
        })
class ProductMcpEndpointTest {

    @TestConfiguration
    static class Config {
        @Bean
        @Primary
        DataEngine fakeDataEngine() {
            return new FakeDataEngine();
        }

        @Bean
        @Primary
        LoaderClient fakeLoaderClient() {
            return new FakeLoaderClient();
        }
    }

    @LocalServerPort
    private int port;

    private McpSyncClient client;

    @BeforeEach
    void connect() {
        var transport = HttpClientStreamableHttpTransport
                .builder("http://localhost:" + port)
                .endpoint("/mcp")
                .jsonMapper(new JacksonMcpJsonMapper(new ObjectMapper()))
                .build();
        client = McpClient.sync(transport).requestTimeout(Duration.ofSeconds(60)).build();
        client.initialize();
    }

    @AfterEach
    void disconnect() {
        client.closeGracefully();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> call(String tool, Map<String, Object> args) {
        CallToolResult result = client.callTool(new CallToolRequest(tool, args));
        assertThat(result.isError()).as("tool %s error: %s", tool, result.content()).isNotEqualTo(true);
        return (Map<String, Object>) result.structuredContent();
    }

    @Test
    void exposesTheProductToolSurface() {
        var names = client.listTools().tools().stream().map(t -> t.name()).toList();
        assertThat(names).contains(
                "list_connections", "introspect_connection", "list_blueprints",
                "create_blueprint", "generate_dataset", "get_job", "list_datasets",
                "get_dataset", "export_dataset", "get_artifacts", "approve_artifacts", "materialize_dataset", "teardown_dataset");
    }

    @Test
    @SuppressWarnings("unchecked")
    void agentFlowCreateGenerateMaterializeTeardown() {
        Map<String, Object> blueprint = call("create_blueprint", Map.of(
                "name", "copilot-demo",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint")),
                        "primary_key", List.of("id"))),
                "volumes", Map.of("customers", 25),
                "seed", 9));
        String blueprintId = (String) blueprint.get("id");

        Map<String, Object> generated = call("generate_dataset",
                Map.of("blueprint_id", blueprintId, "wait_seconds", 30));
        assertThat(generated.get("status")).isEqualTo("succeeded");
        Map<String, Object> dataset = (Map<String, Object>) generated.get("dataset");
        assertThat(dataset.get("status")).isEqualTo("ready");
        String datasetId = (String) dataset.get("id");

        // unconfirmed materialize must come back as a TOOL ERROR the agent can act on
        CallToolResult refused = client.callTool(new CallToolRequest("materialize_dataset",
                Map.of("dataset_id", datasetId, "connection", "warehouse", "confirm", false)));
        assertThat(refused.isError()).isTrue();
        assertThat(refused.content().toString()).contains("confirm");

        // confirmed but UNAPPROVED artifacts -> refused with actionable guidance (FR-L.5)
        CallToolResult unapproved = client.callTool(new CallToolRequest("materialize_dataset",
                Map.of("dataset_id", datasetId, "connection", "warehouse", "confirm", true)));
        assertThat(unapproved.isError()).isTrue();
        assertThat(unapproved.content().toString()).contains("approve");

        // review + approve via the agent surface (a named human act)
        Map<String, Object> artifacts = call("get_artifacts", Map.of("blueprint_id", blueprintId));
        assertThat(artifacts.get("approval")).isEqualTo("pending_approval");
        Map<String, Object> approval = call("approve_artifacts",
                Map.of("blueprint_id", blueprintId, "approved_by", "test human"));
        assertThat(approval.get("approval")).isEqualTo("approved");

        Map<String, Object> materialized = call("materialize_dataset", Map.of(
                "dataset_id", datasetId, "connection", "warehouse",
                "confirm", true, "wait_seconds", 30));
        assertThat(materialized.get("status")).isEqualTo("succeeded");

        Map<String, Object> teardown = call("teardown_dataset", Map.of(
                "dataset_id", datasetId, "connection", "warehouse",
                "confirm", true, "wait_seconds", 30));
        assertThat(teardown.get("status")).isEqualTo("succeeded");
    }
}
