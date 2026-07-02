package io.seedwright.server;

import static org.assertj.core.api.Assertions.assertThat;

import io.seedwright.server.engine.DataEngine;
import io.seedwright.server.loader.LoaderClient;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/**
 * The DB-sink path (FR-G.2/3/4): generate -> materialize into a named connection (explicitly
 * confirmed) -> per-sink record on the Dataset -> teardown. Engine + loader faked.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "spring.datasource.url=jdbc:h2:mem:mattest;DB_CLOSE_DELAY=-1",
            "seedwright.work-dir=${java.io.tmpdir}/seedwright-mat-work",
        })
class MaterializationFlowTest {

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

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private LoaderClient loaderClient;

    private String makeReadyDataset() {
        Map<String, Object> create = Map.of(
                "name", "mat-shop",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint")),
                        "primary_key", List.of("id"))),
                "seed", 1);
        String blueprintId = (String) rest.postForEntity("/api/blueprints", create, Map.class)
                .getBody().get("id");
        Map<?, ?> accepted = rest.postForEntity(
                "/api/blueprints/" + blueprintId + "/datasets", Map.of(), Map.class).getBody();
        String jobId = (String) accepted.get("jobId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + jobId, Map.class).get("status"))
                        .isEqualTo("succeeded"));
        return (String) accepted.get("datasetId");
    }

    @Test
    void materializeRequiresExplicitConfirmation() {
        String datasetId = makeReadyDataset();
        ResponseEntity<Map> refused = rest.postForEntity(
                "/api/datasets/" + datasetId + "/materialize",
                Map.of("connection", "warehouse"), Map.class);
        assertThat(refused.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(refused.getBody().get("error").toString()).contains("confirm");
    }

    @Test
    void materializeThenTeardownRoundtrip() {
        String datasetId = makeReadyDataset();

        ResponseEntity<Map> accepted = rest.postForEntity(
                "/api/datasets/" + datasetId + "/materialize",
                Map.of("connection", "warehouse", "confirm", true), Map.class);
        assertThat(accepted.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        String jobId = (String) accepted.getBody().get("jobId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + jobId, Map.class).get("status"))
                        .isEqualTo("succeeded"));

        Map<?, ?> dataset = rest.getForObject("/api/datasets/" + datasetId, Map.class);
        List<Map<String, Object>> materializations =
                (List<Map<String, Object>>) dataset.get("materializations");
        assertThat(materializations).hasSize(1);
        assertThat(materializations.get(0))
                .containsEntry("connection", "warehouse")
                .containsEntry("status", "loaded")
                .containsEntry("verified", true);

        // loader was driven with the dataset's namespace, replace mode, then verified
        FakeLoaderClient fake = (FakeLoaderClient) loaderClient;
        assertThat(fake.calls).anyMatch(c -> c.startsWith("load:warehouse:ds_") && c.endsWith(":replace"));
        assertThat(fake.calls).anyMatch(c -> c.startsWith("verify:warehouse:ds_"));

        // teardown (also gated)
        ResponseEntity<Map> teardown = rest.postForEntity(
                "/api/datasets/" + datasetId + "/teardown",
                Map.of("connection", "warehouse", "confirm", true), Map.class);
        assertThat(teardown.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        String teardownJob = (String) teardown.getBody().get("jobId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + teardownJob, Map.class).get("status"))
                        .isEqualTo("succeeded"));
        assertThat(fake.calls).anyMatch(c -> c.startsWith("teardown:warehouse:ds_"));
    }

    @Test
    void connectionsEndpointListsNodeConnections() {
        Map<?, ?> response = rest.getForObject("/api/connections", Map.class);
        assertThat((List<String>) response.get("connections")).containsExactly("warehouse");
    }
}
