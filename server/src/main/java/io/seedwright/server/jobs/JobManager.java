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
import io.seedwright.server.loader.LoaderClient;
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
    private final LoaderClient loader;
    private final ObjectMapper json;
    private final Path workDir;
    private final Semaphore slots;
    private final ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();

    public JobManager(BlueprintRepository blueprints,
                      DatasetRepository datasets,
                      JobRepository jobs,
                      DataEngine engine,
                      LoaderClient loader,
                      ObjectMapper json,
                      @Value("${seedwright.work-dir:./data/datasets}") String workDir,
                      @Value("${seedwright.jobs.max-concurrent:4}") int maxConcurrent) {
        this.blueprints = blueprints;
        this.datasets = datasets;
        this.jobs = jobs;
        this.engine = engine;
        this.loader = loader;
        this.json = json;
        // absolute: these paths cross process boundaries (data-engine stdio child shares our
        // cwd, but the jdbc-mcp node is a separate process with its own)
        this.workDir = Path.of(workDir).toAbsolutePath().normalize();
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

    /** FR-L.5 violation: writing to a real database with unapproved (or stale) artifacts. */
    public static class ApprovalRequiredException extends IllegalStateException {
        public ApprovalRequiredException(String message) {
            super(message);
        }
    }

    /**
     * FR-L.5 gate: the EXACT artifacts version that produced this Dataset must be human-approved
     * before it may land in a real database. Fails fast at submission, not inside the job.
     */
    public void requireApprovedArtifacts(DatasetEntity dataset) {
        BlueprintEntity blueprint = blueprints.findById(dataset.getBlueprintId())
                .orElseThrow(() -> new ApprovalRequiredException("blueprint no longer exists"));
        if (!"approved".equals(blueprint.getArtifactsApproval())) {
            throw new ApprovalRequiredException(
                    "generator artifacts are not approved (FR-L.5): review them via "
                            + "GET /api/blueprints/{id}/artifacts and approve via "
                            + "POST /api/blueprints/{id}/approve before loading into a database");
        }
        if (dataset.getArtifactsVersion() != null
                && !dataset.getArtifactsVersion().equals(blueprint.getArtifactsVersion())) {
            throw new ApprovalRequiredException(
                    "this dataset was generated by artifacts " + dataset.getArtifactsVersion()
                            + " but the approved version is " + blueprint.getArtifactsVersion()
                            + " — regenerate the dataset from the approved artifacts");
        }
    }

    /** Materialize a ready Dataset into a named DB connection via the jdbc-mcp node (FR-G.2). */
    public String submitMaterialization(DatasetEntity dataset, String connection, String mode) {
        requireApprovedArtifacts(dataset);
        JobEntity job = newJob("materialize", dataset.getBlueprintId(), dataset.getId());
        executor.submit(() -> runMaterialization(job.getId(), dataset.getId(), connection, mode));
        return job.getId();
    }

    /** Tear a materialization down from a named connection (scoped, idempotent; FR-G.3). */
    public String submitTeardown(DatasetEntity dataset, String connection) {
        JobEntity job = newJob("teardown", dataset.getBlueprintId(), dataset.getId());
        executor.submit(() -> runTeardown(job.getId(), dataset.getId(), connection));
        return job.getId();
    }

    private JobEntity newJob(String type, String blueprintId, String datasetId) {
        JobEntity job = new JobEntity();
        job.setId(UUID.randomUUID().toString());
        job.setType(type);
        job.setStatus("pending");
        job.setBlueprintId(blueprintId);
        job.setDatasetId(datasetId);
        job.setCreatedAt(Instant.now());
        jobs.save(job);
        return job;
    }

    private void runMaterialization(String jobId, String datasetId, String connection, String mode) {
        try {
            slots.acquire();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        }
        try {
            DatasetEntity dataset = datasets.findById(datasetId).orElseThrow();
            Map<String, Object> loadPlan = read(dataset.getLoadPlanJson(), MAP);

            transition(jobId, "running", "exporting jsonl");
            String exportDir = dataset.getCanonicalDir() + "/exports";
            engine.exportDataset(dataset.getCanonicalDir(), loadPlan, exportDir, List.of("jsonl"));

            transition(jobId, "running", "loading via jdbc-mcp: " + connection);
            Map<String, Object> load = loader.loadDataset(
                    connection, exportDir, loadPlan, dataset.getNamespace(), mode);

            transition(jobId, "running", "verifying materialization");
            Map<String, Object> verification =
                    loader.verifyMaterialization(connection, loadPlan, dataset.getNamespace());
            boolean ok = Boolean.TRUE.equals(verification.get("ok"));

            recordMaterialization(datasetId, Map.of(
                    "connection", connection,
                    "namespace", dataset.getNamespace(),
                    "mode", mode,
                    "status", ok ? "loaded" : "verification_failed",
                    "total_rows", load.getOrDefault("total_rows", -1),
                    "verified", ok,
                    "at", Instant.now().toString()));
            finish(jobId, ok ? "succeeded" : "failed",
                    ok ? "materialized to " + connection : "verification failed", null);
        } catch (Exception e) {
            log.error("materialization job {} failed", jobId, e);
            finish(jobId, "failed", "materialization failed", e.toString());
        } finally {
            slots.release();
        }
    }

    private void runTeardown(String jobId, String datasetId, String connection) {
        try {
            slots.acquire();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        }
        try {
            DatasetEntity dataset = datasets.findById(datasetId).orElseThrow();
            transition(jobId, "running", "tearing down via jdbc-mcp: " + connection);
            Map<String, Object> result = loader.teardownDataset(connection, dataset.getNamespace());
            recordMaterialization(datasetId, Map.of(
                    "connection", connection,
                    "namespace", dataset.getNamespace(),
                    "status", "torn_down",
                    "existed", result.getOrDefault("existed", false),
                    "at", Instant.now().toString()));
            finish(jobId, "succeeded", "teardown complete on " + connection, null);
        } catch (Exception e) {
            log.error("teardown job {} failed", jobId, e);
            finish(jobId, "failed", "teardown failed", e.toString());
        } finally {
            slots.release();
        }
    }

    private void recordMaterialization(String datasetId, Map<String, Object> record) {
        updateDataset(datasetId, ds -> {
            List<Map<String, Object>> records = ds.getMaterializationsJson() == null
                    ? new java.util.ArrayList<>()
                    : new java.util.ArrayList<>(read(ds.getMaterializationsJson(), LIST));
            records.add(record);
            ds.setMaterializationsJson(write(records));
        });
    }

    /** Preview / dry-run (FR-E.6): author-if-needed + a small in-memory sample. Synchronous. */
    public Map<String, Object> preview(BlueprintEntity blueprint, int rowsPerTable) {
        Map<String, Object> artifacts = ensureArtifacts(blueprint);
        return engine.previewDataset(artifacts, read(blueprint.getSchemaJson(), MAP), rowsPerTable);
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
                blueprint.getSeed(),
                blueprint.getProvider());
        blueprint.setArtifactsJson(write(artifacts));
        blueprint.setArtifactsVersion((String) artifacts.get("version"));
        // fresh artifacts are unapproved by definition (FR-L.5)
        blueprint.setArtifactsApproval("pending_approval");
        blueprint.setArtifactsApprovedBy(null);
        blueprint.setArtifactsApprovedAt(null);
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
