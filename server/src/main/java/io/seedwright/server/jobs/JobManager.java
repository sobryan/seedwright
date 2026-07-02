package io.seedwright.server.jobs;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.domain.BlueprintEntity;
import io.seedwright.server.domain.BlueprintRepository;
import io.seedwright.server.domain.DatasetEntity;
import io.seedwright.server.domain.DatasetRepository;
import io.seedwright.server.domain.JobEntity;
import io.seedwright.server.domain.JobRepository;
import io.seedwright.server.engine.DataEngine;
import jakarta.annotation.PreDestroy;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;

/**
 * Async job execution (FR-I.2, FR-E.4): virtual-thread-per-job, bounded by a semaphore (each
 * generation is CPU/RAM-heavy in the engine), with the durable record in the {@code job} table.
 * A Dataset is marked {@code ready} only after generation AND validation succeed — failure or a
 * crash leaves {@code failed}/{@code quarantined}, never a silent partial. On startup, jobs left
 * {@code running} by a sudden restart are reconciled to {@code failed} (a retry is a
 * deterministic re-run).
 */
@Service
public class JobManager {

    private static final Logger log = LoggerFactory.getLogger(JobManager.class);
    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {};
    private static final TypeReference<List<Map<String, Object>>> LIST = new TypeReference<>() {};

    private final BlueprintRepository blueprints;
    private final DatasetRepository datasets;
    private final JobRepository jobs;
    private final DataEngine engine;
    private final ObjectMapper json;
    private final Path workDir;
    private final Semaphore slots;
    private final ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();

    public JobManager(BlueprintRepository blueprints,
                      DatasetRepository datasets,
                      JobRepository jobs,
                      DataEngine engine,
                      ObjectMapper json,
                      @Value("${seedwright.work-dir:./data/datasets}") String workDir,
                      @Value("${seedwright.jobs.max-concurrent:4}") int maxConcurrent) {
        this.blueprints = blueprints;
        this.datasets = datasets;
        this.jobs = jobs;
        this.engine = engine;
        this.json = json;
        this.workDir = Path.of(workDir);
        this.slots = new Semaphore(maxConcurrent);
    }

    /** Reconcile jobs orphaned by a sudden restart: they are not running anymore. */
    @EventListener(ApplicationReadyEvent.class)
    public void reconcileOrphanedJobs() {
        for (JobEntity job : jobs.findByStatus("running")) {
            job.setStatus("failed");
            job.setError("orphaned by server restart; re-trigger for a deterministic re-run");
            job.setFinishedAt(Instant.now());
            jobs.save(job);
            if (job.getDatasetId() != null) {
                datasets.findById(job.getDatasetId()).ifPresent(ds -> {
                    ds.setStatus("failed");
                    datasets.save(ds);
                });
            }
            log.warn("reconciled orphaned job {} to failed", job.getId());
        }
    }

    public record GenerationHandles(String jobId, String datasetId) {}

    /** Create the Dataset + Job records and run authoring→generation→validation async. */
    public GenerationHandles submitGeneration(BlueprintEntity blueprint, String datasetName) {
        String datasetId = UUID.randomUUID().toString();
        String namespace = "ds_" + datasetId.replace("-", "");

        DatasetEntity dataset = new DatasetEntity();
        dataset.setId(datasetId);
        dataset.setBlueprintId(blueprint.getId());
        dataset.setName(datasetName);
        dataset.setStatus("pending");
        dataset.setNamespace(namespace);
        dataset.setCreatedAt(Instant.now());
        datasets.save(dataset);

        JobEntity job = new JobEntity();
        job.setId(UUID.randomUUID().toString());
        job.setType("generate");
        job.setStatus("pending");
        job.setBlueprintId(blueprint.getId());
        job.setDatasetId(datasetId);
        job.setCreatedAt(Instant.now());
        jobs.save(job);

        executor.submit(() -> runGeneration(job.getId(), blueprint.getId(), datasetId, namespace));
        return new GenerationHandles(job.getId(), datasetId);
    }

    private void runGeneration(String jobId, String blueprintId, String datasetId, String namespace) {
        try {
            slots.acquire();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        }
        try {
            transition(jobId, "running", "authoring");
            BlueprintEntity blueprint = blueprints.findById(blueprintId).orElseThrow();
            Map<String, Object> artifacts = ensureArtifacts(blueprint);

            transition(jobId, "running", "generating");
            updateDataset(datasetId, ds -> ds.setStatus("generating"));
            Map<String, Object> generation = engine.generateDataset(
                    artifacts,
                    read(blueprint.getSchemaJson(), MAP),
                    workDir.resolve(datasetId).toString(),
                    namespace);

            transition(jobId, "running", "validating");
            @SuppressWarnings("unchecked")
            Map<String, Object> loadPlan = (Map<String, Object>) generation.get("load_plan");
            List<Map<String, Object>> dataTests = readTests(artifacts);
            Map<String, Object> report = engine.validateDataset(
                    (String) generation.get("canonical_dir"), loadPlan, dataTests);

            boolean passed = Boolean.TRUE.equals(report.get("passed"));
            updateDataset(datasetId, ds -> {
                ds.setStatus(passed ? "ready" : "quarantined");
                ds.setCanonicalDir((String) generation.get("canonical_dir"));
                ds.setSeed(asLong(generation.get("seed")));
                ds.setArtifactsVersion((String) generation.get("artifacts_version"));
                ds.setRowCountsJson(write(generation.get("row_counts")));
                ds.setLoadPlanJson(write(loadPlan));
                ds.setValidationReportJson(write(report));
            });
            finish(jobId, "succeeded", passed ? "dataset ready" : "validation failed: quarantined", null);
        } catch (Exception e) {
            log.error("generation job {} failed", jobId, e);
            updateDataset(datasetId, ds -> ds.setStatus("failed"));
            finish(jobId, "failed", "generation failed", e.toString());
        } finally {
            slots.release();
        }
    }

    private Map<String, Object> ensureArtifacts(BlueprintEntity blueprint) {
        if (blueprint.getArtifactsJson() != null) {
            return read(blueprint.getArtifactsJson(), MAP);
        }
        Map<String, Object> artifacts = engine.authorGenerator(
                read(blueprint.getSchemaJson(), MAP),
                blueprint.getRulesJson() == null ? List.of() : read(blueprint.getRulesJson(), LIST),
                blueprint.getForeignKeysJson() == null ? null : read(blueprint.getForeignKeysJson(), MAP),
                blueprint.getVolumesJson() == null ? null : read(blueprint.getVolumesJson(), MAP),
                blueprint.getSeed());
        blueprint.setArtifactsJson(write(artifacts));
        blueprint.setArtifactsVersion((String) artifacts.get("version"));
        blueprint.setUpdatedAt(Instant.now());
        blueprints.save(blueprint);
        return artifacts;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> readTests(Map<String, Object> artifacts) {
        Object tests = artifacts.get("data_tests");
        return tests instanceof List<?> list ? (List<Map<String, Object>>) list : List.of();
    }

    private void transition(String jobId, String status, String message) {
        jobs.findById(jobId).ifPresent(job -> {
            if (job.getStartedAt() == null) {
                job.setStartedAt(Instant.now());
            }
            job.setStatus(status);
            job.setMessage(message);
            jobs.save(job);
        });
    }

    private void finish(String jobId, String status, String message, String error) {
        jobs.findById(jobId).ifPresent(job -> {
            job.setStatus(status);
            job.setMessage(message);
            job.setError(error);
            job.setFinishedAt(Instant.now());
            jobs.save(job);
        });
    }

    private void updateDataset(String datasetId, java.util.function.Consumer<DatasetEntity> change) {
        datasets.findById(datasetId).ifPresent(ds -> {
            change.accept(ds);
            datasets.save(ds);
        });
    }

    private <T> T read(String jsonText, TypeReference<T> type) {
        try {
            return json.readValue(jsonText, type);
        } catch (Exception e) {
            throw new IllegalStateException("corrupt JSON aggregate in metadata store", e);
        }
    }

    private String write(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("unserializable engine result", e);
        }
    }

    private Long asLong(Object value) {
        return value instanceof Number n ? n.longValue() : null;
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }
}
