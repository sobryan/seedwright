package io.seedwright.server;

import static org.assertj.core.api.Assertions.assertThat;

import io.seedwright.server.engine.DataEngine;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.awaitility.Awaitility;

/**
 * End-to-end REST flow (spec FR-I): create Blueprint -> trigger generation (202 + Job) ->
 * job succeeds -> Dataset is 'ready' with a validation report. Engine faked (NFR-TEST).
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "spring.datasource.url=jdbc:h2:mem:flowtest;DB_CLOSE_DELAY=-1",
            "seedwright.work-dir=${java.io.tmpdir}/seedwright-test-work",
        })
class ServerFlowTest {

    @TestConfiguration
    static class Config {
        @Bean
        @Primary
        DataEngine fakeDataEngine() {
            return new FakeDataEngine();
        }
    }

    @Autowired
    private TestRestTemplate rest;

    @Test
    void createBlueprintTriggerGenerationAndReachReady() {
        Map<String, Object> create = Map.of(
                "name", "shop",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint")),
                        "primary_key", List.of("id"))),
                "rules", List.of(),
                "volumes", Map.of("customers", 40),
                "seed", 42);

        ResponseEntity<Map> created = rest.postForEntity("/api/blueprints", create, Map.class);
        assertThat(created.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        String blueprintId = (String) created.getBody().get("id");

        ResponseEntity<Map> accepted =
                rest.postForEntity("/api/blueprints/" + blueprintId + "/datasets", Map.of(), Map.class);
        assertThat(accepted.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        String jobId = (String) accepted.getBody().get("jobId");
        String datasetId = (String) accepted.getBody().get("datasetId");

        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
            Map<?, ?> job = rest.getForObject("/api/jobs/" + jobId, Map.class);
            assertThat(job.get("status")).isEqualTo("succeeded");
        });

        Map<?, ?> dataset = rest.getForObject("/api/datasets/" + datasetId, Map.class);
        assertThat(dataset.get("status")).isEqualTo("ready");
        assertThat(dataset.get("namespace").toString()).startsWith("ds_");
        assertThat(((Map<?, ?>) dataset.get("validationReport")).get("passed")).isEqualTo(true);

        // artifacts were authored once and cached on the blueprint
        Map<?, ?> blueprint = rest.getForObject("/api/blueprints/" + blueprintId, Map.class);
        assertThat(blueprint.get("artifactsVersion")).isEqualTo("ga_fake0000");
    }

    @Test
    void unknownBlueprintYields404OnTrigger() {
        ResponseEntity<Map> response =
                rest.postForEntity("/api/blueprints/nope/datasets", Map.of(), Map.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void previewReturnsSampleRowsWithoutMaterializing() {
        Map<String, Object> create = Map.of(
                "name", "preview-shop",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint")),
                        "primary_key", List.of("id"))),
                "seed", 42);
        String blueprintId = (String) rest.postForEntity("/api/blueprints", create, Map.class)
                .getBody().get("id");

        Map<?, ?> preview = rest.postForObject(
                "/api/blueprints/" + blueprintId + "/preview?rows=5", Map.of(), Map.class);
        assertThat(preview.get("sampled")).isEqualTo(true);
        assertThat(((Map<?, ?>) preview.get("tables")).get("customers")).isNotNull();
    }

    @Test
    void rowsEndpointPagesThroughDataset() {
        Map<String, Object> create = Map.of(
                "name", "rows-shop",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint")),
                        "primary_key", List.of("id"))),
                "seed", 42);
        String blueprintId = (String) rest.postForEntity("/api/blueprints", create, Map.class)
                .getBody().get("id");
        Map<?, ?> accepted = rest.postForEntity(
                "/api/blueprints/" + blueprintId + "/datasets", Map.of(), Map.class).getBody();
        String jobId = (String) accepted.get("jobId");
        String datasetId = (String) accepted.get("datasetId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + jobId, Map.class).get("status"))
                        .isEqualTo("succeeded"));

        Map<?, ?> page = rest.getForObject(
                "/api/datasets/" + datasetId + "/rows?table=customers&offset=5&limit=10", Map.class);
        assertThat(page.get("total_rows")).isEqualTo(40);
        assertThat((List<?>) page.get("rows")).isNotEmpty();
    }

    @Test
    void refinementSuggestsRulesThenUpdatingThemClearsArtifactsAndApproval() {
        Map<String, Object> create = Map.of(
                "name", "refine-shop",
                "schema", Map.of("customers", Map.of(
                        "columns", List.of(Map.of("name", "id", "sql_type", "bigint"),
                                Map.of("name", "tier", "sql_type", "varchar(20)")),
                        "primary_key", List.of("id"))),
                "seed", 42);
        String blueprintId = (String) rest.postForEntity("/api/blueprints", create, Map.class)
                .getBody().get("id");
        Map<?, ?> accepted = rest.postForEntity(
                "/api/blueprints/" + blueprintId + "/datasets", Map.of(), Map.class).getBody();
        String jobId = (String) accepted.get("jobId");
        String datasetId = (String) accepted.get("datasetId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + jobId, Map.class).get("status"))
                        .isEqualTo("succeeded"));

        // artifacts got authored + cached by generation
        Map<?, ?> before = rest.getForObject("/api/blueprints/" + blueprintId, Map.class);
        assertThat(before.get("artifactsVersion")).isNotNull();

        // FR-D: profile the dataset -> a rule suggestion the user can adopt
        Map<?, ?> suggestions = rest.getForObject(
                "/api/datasets/" + datasetId + "/suggestions", Map.class);
        List<Map<String, Object>> list = (List<Map<String, Object>>) suggestions.get("suggestions");
        assertThat(list).isNotEmpty();
        Map<String, Object> rule = (Map<String, Object>) list.get(0).get("rule");

        // apply it -> rules replaced, cached artifacts + approval invalidated (must re-author)
        ResponseEntity<Map> updated = rest.exchange(
                "/api/blueprints/" + blueprintId + "/rules", HttpMethod.PUT,
                new HttpEntity<>(Map.of("rules", List.of(rule))), Map.class);
        assertThat(updated.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(updated.getBody().get("artifactsVersion")).isNull();
        assertThat(updated.getBody().get("artifactsApproval")).isNull();

        // regenerating re-authors against the new rules (fresh artifacts appear)
        Map<?, ?> regen = rest.postForEntity(
                "/api/blueprints/" + blueprintId + "/datasets", Map.of(), Map.class).getBody();
        String regenJob = (String) regen.get("jobId");
        Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(rest.getForObject("/api/jobs/" + regenJob, Map.class).get("status"))
                        .isEqualTo("succeeded"));
        Map<?, ?> after = rest.getForObject("/api/blueprints/" + blueprintId, Map.class);
        assertThat(after.get("artifactsVersion")).isNotNull();
    }
}
