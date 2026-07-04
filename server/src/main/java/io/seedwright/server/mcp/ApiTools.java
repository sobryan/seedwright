package io.seedwright.server.mcp;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.seedwright.server.domain.BlueprintEntity;
import io.seedwright.server.domain.BlueprintRepository;
import io.seedwright.server.domain.BlueprintService;
import io.seedwright.server.domain.DatasetEntity;
import io.seedwright.server.domain.DatasetRepository;
import io.seedwright.server.domain.JobEntity;
import io.seedwright.server.domain.JobRepository;
import io.seedwright.server.engine.DataEngine;
import io.seedwright.server.jobs.JobManager;
import io.seedwright.server.loader.LoaderClient;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * seedwright's product surface as MCP tools (ADR-0004 integration tier) — what lets GitHub
 * Copilot CLI (or any MCP client) drive the on-prem install conversationally: introspect a
 * database, create a Blueprint, generate a Dataset, export files, materialize into a DB.
 *
 * <p>Safety carries over verbatim: {@code materialize_dataset}/{@code teardown_dataset} REQUIRE
 * {@code confirm=true} (FR-G.4) — the tool descriptions instruct the agent to ask its human
 * first — and credentials never appear here (they live on the jdbc-mcp node, spec §7).
 */
@Component
public class ApiTools {

    private static final Logger log = LoggerFactory.getLogger(ApiTools.class);
    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {};
    private static final int MAX_WAIT_SECONDS = 600;

    private final BlueprintRepository blueprints;
    private final BlueprintService blueprintService;
    private final DatasetRepository datasets;
    private final JobRepository jobs;
    private final JobManager jobManager;
    private final DataEngine engine;
    private final LoaderClient loader;
    private final ObjectMapper json;

    public ApiTools(BlueprintRepository blueprints, BlueprintService blueprintService,
                    DatasetRepository datasets, JobRepository jobs, JobManager jobManager,
                    DataEngine engine, LoaderClient loader, ObjectMapper json) {
        this.blueprints = blueprints;
        this.blueprintService = blueprintService;
        this.datasets = datasets;
        this.jobs = jobs;
        this.jobManager = jobManager;
        this.engine = engine;
        this.loader = loader;
        this.json = json;
    }

    public List<SyncToolSpecification> specifications() {
        return List.of(
                spec("list_connections",
                        "List the datastore connections configured on the jdbc-mcp node (names only)",
                        Map.of("type", "object", "properties", Map.of()),
                        args -> Map.of("connections", loader.listConnections())),

                spec("introspect_connection",
                        "Introspect a database connection's tables/columns/keys. The result's "
                                + "'schema' and 'foreign_keys' plug directly into create_blueprint.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "connection", Map.of("type", "string"),
                                        "schema", Map.of("type", "string",
                                                "description", "optional schema pattern")),
                                "required", List.of("connection")),
                        args -> loader.introspectSchema((String) args.get("connection"),
                                (String) args.get("schema"))),

                spec("list_blueprints",
                        "List Blueprints (generation specs)",
                        Map.of("type", "object", "properties", Map.of()),
                        args -> Map.of("blueprints",
                                blueprints.findAll().stream().map(this::blueprintSummary).toList())),

                spec("create_blueprint",
                        "Create a Blueprint. schema = {table: {columns: [{name, sql_type}], "
                                + "primary_key: [..]}}; foreign_keys = {table: [{column, "
                                + "references_table, references_column, min_per_parent, "
                                + "max_per_parent}]}; rules = [{table, column, enum|min_value|"
                                + "max_value}]; volumes = {table: row_count}; provider = "
                                + "'heuristic' (default, no LLM) or 'copilot-cli' (GitHub "
                                + "Copilot CLI authors the generator).",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "name", Map.of("type", "string"),
                                        "description", Map.of("type", "string"),
                                        "schema", Map.of("type", "object"),
                                        "rules", Map.of("type", "array"),
                                        "foreign_keys", Map.of("type", "object"),
                                        "volumes", Map.of("type", "object"),
                                        "seed", Map.of("type", "integer"),
                                        "provider", Map.of("type", "string")),
                                "required", List.of("name", "schema")),
                        this::createBlueprint),

                spec("get_artifacts",
                        "Inspect a Blueprint's authored Generator Artifacts (the declarative "
                                + "genspec + data-tests + provenance) — what a human reviews "
                                + "before approving (FR-L.5).",
                        Map.of("type", "object",
                                "properties", Map.of("blueprint_id", Map.of("type", "string")),
                                "required", List.of("blueprint_id")),
                        args -> {
                            BlueprintEntity bp = blueprints
                                    .findById((String) args.get("blueprint_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such blueprint"));
                            if (bp.getArtifactsJson() == null) {
                                throw new IllegalStateException(
                                        "no artifacts yet — generate or preview first");
                            }
                            Map<String, Object> out = new LinkedHashMap<>();
                            out.put("artifactsVersion", bp.getArtifactsVersion());
                            out.put("approval", bp.getArtifactsApproval());
                            out.put("approvedBy", bp.getArtifactsApprovedBy());
                            out.put("artifacts", read(bp.getArtifactsJson()));
                            return out;
                        }),

                spec("approve_artifacts",
                        "Record HUMAN approval of a Blueprint's current artifacts (FR-L.5) — "
                                + "required before any database materialization. Approval is a "
                                + "human act: only call this after the user has reviewed the "
                                + "artifacts and explicitly said to approve, and pass THEIR name "
                                + "as approved_by.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "blueprint_id", Map.of("type", "string"),
                                        "approved_by", Map.of("type", "string")),
                                "required", List.of("blueprint_id", "approved_by")),
                        args -> {
                            BlueprintEntity bp = blueprints
                                    .findById((String) args.get("blueprint_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such blueprint"));
                            String approver = (String) args.get("approved_by");
                            if (bp.getArtifactsJson() == null) {
                                throw new IllegalStateException(
                                        "no artifacts to approve — generate or preview first");
                            }
                            if (approver == null || approver.isBlank()) {
                                throw new IllegalArgumentException(
                                        "approved_by is required — approval is a named human act");
                            }
                            bp.setArtifactsApproval("approved");
                            bp.setArtifactsApprovedBy(approver.trim());
                            bp.setArtifactsApprovedAt(java.time.Instant.now());
                            blueprints.save(bp);
                            return Map.of("artifactsVersion", bp.getArtifactsVersion(),
                                    "approval", "approved", "approvedBy", approver.trim());
                        }),

                spec("preview_blueprint",
                        "Preview a small sample of what a Blueprint would generate (dry-run, "
                                + "no files, no database). Authors the generator first if needed.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "blueprint_id", Map.of("type", "string"),
                                        "rows_per_table", Map.of("type", "integer")),
                                "required", List.of("blueprint_id")),
                        args -> {
                            BlueprintEntity blueprint = blueprints
                                    .findById((String) args.get("blueprint_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such blueprint"));
                            int rows = args.get("rows_per_table") instanceof Number n
                                    ? n.intValue() : 10;
                            return jobManager.preview(blueprint, Math.max(1, Math.min(rows, 50)));
                        }),

                spec("read_dataset_rows",
                        "Read a page of rows from a generated Dataset's canonical data",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "dataset_id", Map.of("type", "string"),
                                        "table", Map.of("type", "string"),
                                        "offset", Map.of("type", "integer"),
                                        "limit", Map.of("type", "integer")),
                                "required", List.of("dataset_id", "table")),
                        args -> {
                            DatasetEntity dataset = datasets
                                    .findById((String) args.get("dataset_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such dataset"));
                            if (dataset.getCanonicalDir() == null) {
                                throw new IllegalStateException("dataset has no canonical data yet");
                            }
                            return engine.readRows(
                                    dataset.getCanonicalDir(),
                                    (String) args.get("table"),
                                    args.get("offset") instanceof Number o ? o.intValue() : 0,
                                    args.get("limit") instanceof Number l ? l.intValue() : 50);
                        }),

                spec("suggest_rules",
                        "Profile a generated Dataset and propose rules that would tighten the "
                                + "Blueprint (low-cardinality columns -> enum, numeric spread -> "
                                + "range, observed nulls -> null-rate). Feed chosen suggestions "
                                + "to update_blueprint_rules, then regenerate to refine (FR-D).",
                        Map.of("type", "object",
                                "properties", Map.of("dataset_id", Map.of("type", "string")),
                                "required", List.of("dataset_id")),
                        args -> {
                            DatasetEntity dataset = datasets
                                    .findById((String) args.get("dataset_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such dataset"));
                            if (dataset.getCanonicalDir() == null || dataset.getLoadPlanJson() == null) {
                                throw new IllegalStateException("dataset has no canonical data yet");
                            }
                            List<Map<String, Object>> existing = blueprints
                                    .findById(dataset.getBlueprintId())
                                    .map(bp -> bp.getRulesJson() == null
                                            ? List.<Map<String, Object>>of() : readList(bp.getRulesJson()))
                                    .orElse(List.of());
                            return engine.suggestRules(dataset.getCanonicalDir(),
                                    read(dataset.getLoadPlanJson()), existing);
                        }),

                spec("update_blueprint_rules",
                        "Replace a Blueprint's rules to refine it (FR-D). This invalidates the "
                                + "cached generator artifacts and any approval — the next "
                                + "generate_dataset re-authors against the new rules. Existing "
                                + "Datasets are untouched.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "blueprint_id", Map.of("type", "string"),
                                        "rules", Map.of("type", "array",
                                                "items", Map.of("type", "object"))),
                                "required", List.of("blueprint_id", "rules")),
                        args -> {
                            BlueprintEntity bp = blueprints
                                    .findById((String) args.get("blueprint_id"))
                                    .orElseThrow(() -> new IllegalArgumentException("no such blueprint"));
                            bp.setRulesJson(writeJson(args.get("rules")));
                            bp.setArtifactsJson(null);
                            bp.setArtifactsVersion(null);
                            bp.setArtifactsApproval(null);
                            bp.setArtifactsApprovedBy(null);
                            bp.setArtifactsApprovedAt(null);
                            bp.setUpdatedAt(java.time.Instant.now());
                            blueprints.save(bp);
                            return Map.of("id", bp.getId(), "rulesUpdated", true,
                                    "artifactsCleared", true);
                        }),

                spec("generate_dataset",
                        "Generate a Dataset from a Blueprint (authoring + deterministic "
                                + "generation + validation). Waits up to wait_seconds (default 120) "
                                + "for completion; check get_job if still running.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "blueprint_id", Map.of("type", "string"),
                                        "wait_seconds", Map.of("type", "integer")),
                                "required", List.of("blueprint_id")),
                        this::generateDataset),

                spec("get_job",
                        "Get an async job's status/message/error",
                        Map.of("type", "object",
                                "properties", Map.of("job_id", Map.of("type", "string")),
                                "required", List.of("job_id")),
                        args -> jobs.findById((String) args.get("job_id"))
                                .map(this::jobSummary)
                                .orElseThrow(() -> new IllegalArgumentException("no such job"))),

                spec("list_datasets",
                        "List a Blueprint's Datasets",
                        Map.of("type", "object",
                                "properties", Map.of("blueprint_id", Map.of("type", "string")),
                                "required", List.of("blueprint_id")),
                        args -> Map.of("datasets", datasets
                                .findByBlueprintIdOrderByCreatedAtDesc((String) args.get("blueprint_id"))
                                .stream().map(this::datasetSummary).toList())),

                spec("get_dataset",
                        "Get a Dataset (status, row counts, validation report, materializations)",
                        Map.of("type", "object",
                                "properties", Map.of("dataset_id", Map.of("type", "string")),
                                "required", List.of("dataset_id")),
                        args -> datasets.findById((String) args.get("dataset_id"))
                                .map(this::datasetSummary)
                                .orElseThrow(() -> new IllegalArgumentException("no such dataset"))),

                spec("export_dataset",
                        "Export a ready Dataset's canonical data to files (csv, jsonl, sql)",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "dataset_id", Map.of("type", "string"),
                                        "formats", Map.of("type", "array",
                                                "items", Map.of("type", "string"))),
                                "required", List.of("dataset_id")),
                        this::exportDataset),

                spec("materialize_dataset",
                        "Load a ready Dataset into a named database connection. SIDE-EFFECTING: "
                                + "writes to a real database (into an isolated ds_ schema). You "
                                + "MUST ask the user for confirmation and pass confirm=true "
                                + "(refused otherwise). Waits for the load like generate_dataset.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "dataset_id", Map.of("type", "string"),
                                        "connection", Map.of("type", "string"),
                                        "mode", Map.of("type", "string",
                                                "description", "create|replace (default replace)"),
                                        "confirm", Map.of("type", "boolean"),
                                        "wait_seconds", Map.of("type", "integer")),
                                "required", List.of("dataset_id", "connection", "confirm")),
                        this::materializeDataset),

                spec("teardown_dataset",
                        "Remove a Dataset's materialization from a database connection (drops only "
                                + "its isolated ds_ schema). SIDE-EFFECTING: ask the user first and "
                                + "pass confirm=true.",
                        Map.of("type", "object",
                                "properties", Map.of(
                                        "dataset_id", Map.of("type", "string"),
                                        "connection", Map.of("type", "string"),
                                        "confirm", Map.of("type", "boolean"),
                                        "wait_seconds", Map.of("type", "integer")),
                                "required", List.of("dataset_id", "connection", "confirm")),
                        this::teardownDataset));
    }

    // --- handlers ---------------------------------------------------------------------

    private Object createBlueprint(Map<String, Object> args) {
        BlueprintEntity entity = blueprintService.create(
                (String) args.get("name"),
                (String) args.get("description"),
                asMap(args.get("schema")),
                asList(args.get("rules")),
                asMap(args.get("foreign_keys")),
                asMap(args.get("volumes")),
                args.get("seed") instanceof Number n ? n.longValue() : null,
                (String) args.get("provider"));
        return blueprintSummary(entity);
    }

    private Object generateDataset(Map<String, Object> args) throws InterruptedException {
        BlueprintEntity blueprint = blueprints.findById((String) args.get("blueprint_id"))
                .orElseThrow(() -> new IllegalArgumentException("no such blueprint"));
        JobManager.GenerationHandles handles = jobManager.submitGeneration(blueprint, null);
        JobEntity job = awaitJob(handles.jobId(), waitSeconds(args, 120));
        Map<String, Object> out = new LinkedHashMap<>(jobSummary(job));
        datasets.findById(handles.datasetId())
                .ifPresent(ds -> out.put("dataset", datasetSummary(ds)));
        return out;
    }

    private Object exportDataset(Map<String, Object> args) {
        DatasetEntity dataset = requireReadyDataset((String) args.get("dataset_id"));
        List<String> formats = asStringList(args.get("formats"));
        return engine.exportDataset(
                dataset.getCanonicalDir(),
                read(dataset.getLoadPlanJson()),
                dataset.getCanonicalDir() + "/exports",
                formats.isEmpty() ? List.of("csv") : formats);
    }

    private Object materializeDataset(Map<String, Object> args) throws InterruptedException {
        requireConfirmation(args, "materialize_dataset writes to a database");
        DatasetEntity dataset = requireReadyDataset((String) args.get("dataset_id"));
        String mode = args.get("mode") == null ? "replace" : args.get("mode").toString();
        String jobId = jobManager.submitMaterialization(
                dataset, (String) args.get("connection"), mode);
        JobEntity job = awaitJob(jobId, waitSeconds(args, 120));
        Map<String, Object> out = new LinkedHashMap<>(jobSummary(job));
        datasets.findById(dataset.getId())
                .ifPresent(ds -> out.put("dataset", datasetSummary(ds)));
        return out;
    }

    private Object teardownDataset(Map<String, Object> args) throws InterruptedException {
        requireConfirmation(args, "teardown_dataset deletes from a database");
        DatasetEntity dataset = datasets.findById((String) args.get("dataset_id"))
                .orElseThrow(() -> new IllegalArgumentException("no such dataset"));
        String jobId = jobManager.submitTeardown(dataset, (String) args.get("connection"));
        return jobSummary(awaitJob(jobId, waitSeconds(args, 120)));
    }

    // --- helpers ----------------------------------------------------------------------

    private void requireConfirmation(Map<String, Object> args, String what) {
        if (!Boolean.TRUE.equals(args.get("confirm"))) {
            throw new IllegalArgumentException(
                    what + " and is refused without confirm=true — ask the user for explicit "
                            + "confirmation first (FR-G.4)");
        }
    }

    private DatasetEntity requireReadyDataset(String id) {
        DatasetEntity dataset = datasets.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("no such dataset"));
        if (!"ready".equals(dataset.getStatus())) {
            throw new IllegalStateException("dataset is not ready (status=" + dataset.getStatus()
                    + "); generate first or check its validation report");
        }
        return dataset;
    }

    private JobEntity awaitJob(String jobId, int waitSeconds) throws InterruptedException {
        long deadline = System.nanoTime() + waitSeconds * 1_000_000_000L;
        while (true) {
            JobEntity job = jobs.findById(jobId).orElseThrow();
            boolean done = "succeeded".equals(job.getStatus()) || "failed".equals(job.getStatus());
            if (done || System.nanoTime() > deadline) {
                return job;
            }
            Thread.sleep(300);
        }
    }

    private int waitSeconds(Map<String, Object> args, int fallback) {
        int requested = args.get("wait_seconds") instanceof Number n ? n.intValue() : fallback;
        return Math.max(0, Math.min(requested, MAX_WAIT_SECONDS));
    }

    private Map<String, Object> blueprintSummary(BlueprintEntity entity) {
        Map<String, Object> dto = new LinkedHashMap<>();
        dto.put("id", entity.getId());
        dto.put("name", entity.getName());
        dto.put("status", entity.getStatus());
        dto.put("seed", entity.getSeed());
        dto.put("artifactsVersion", entity.getArtifactsVersion());
        dto.put("provider", entity.getProvider());
        return dto;
    }

    private Map<String, Object> jobSummary(JobEntity job) {
        Map<String, Object> dto = new LinkedHashMap<>();
        dto.put("jobId", job.getId());
        dto.put("type", job.getType());
        dto.put("status", job.getStatus());
        dto.put("message", job.getMessage());
        dto.put("error", job.getError());
        dto.put("datasetId", job.getDatasetId());
        return dto;
    }

    private Map<String, Object> datasetSummary(DatasetEntity entity) {
        Map<String, Object> dto = new LinkedHashMap<>();
        dto.put("id", entity.getId());
        dto.put("blueprintId", entity.getBlueprintId());
        dto.put("status", entity.getStatus());
        dto.put("namespace", entity.getNamespace());
        dto.put("rowCounts", readNullable(entity.getRowCountsJson()));
        dto.put("validationReport", readNullable(entity.getValidationReportJson()));
        dto.put("materializations", readNullable(entity.getMaterializationsJson()));
        return dto;
    }

    private Map<String, Object> read(String text) {
        try {
            return json.readValue(text, MAP);
        } catch (Exception e) {
            throw new IllegalStateException("corrupt JSON aggregate", e);
        }
    }

    private static final TypeReference<List<Map<String, Object>>> LIST = new TypeReference<>() {};

    private List<Map<String, Object>> readList(String text) {
        try {
            return json.readValue(text, LIST);
        } catch (Exception e) {
            throw new IllegalStateException("corrupt JSON aggregate", e);
        }
    }

    private String writeJson(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("cannot serialize", e);
        }
    }

    private Object readNullable(String text) {
        if (text == null) {
            return null;
        }
        try {
            return json.readValue(text, Object.class);
        } catch (Exception e) {
            throw new IllegalStateException("corrupt JSON aggregate", e);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        return value == null ? null : (Map<String, Object>) value;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asList(Object value) {
        return value == null ? null : (List<Map<String, Object>>) value;
    }

    @SuppressWarnings("unchecked")
    private static List<String> asStringList(Object value) {
        return value == null ? List.of() : (List<String>) value;
    }

    // --- MCP plumbing (same shape as the jdbc-mcp node) --------------------------------

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
                        log.warn("mcp tool {} failed", name, e);
                        return CallToolResult.builder()
                                .isError(true)
                                .content(List.of(new McpSchema.TextContent(
                                        e.getClass().getSimpleName() + ": " + e.getMessage())))
                                .build();
                    }
                })
                .build();
    }
}
