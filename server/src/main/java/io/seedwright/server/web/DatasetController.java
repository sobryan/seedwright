package io.seedwright.server.web;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.domain.DatasetEntity;
import io.seedwright.server.domain.DatasetRepository;
import io.seedwright.server.engine.DataEngine;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class DatasetController {

    private final DatasetRepository datasets;
    private final DataEngine engine;
    private final io.seedwright.server.jobs.JobManager jobManager;
    private final ObjectMapper json;

    public DatasetController(DatasetRepository datasets, DataEngine engine,
                             io.seedwright.server.jobs.JobManager jobManager, ObjectMapper json) {
        this.datasets = datasets;
        this.engine = engine;
        this.jobManager = jobManager;
        this.json = json;
    }

    @GetMapping("/blueprints/{blueprintId}/datasets")
    public List<Map<String, Object>> listForBlueprint(@PathVariable String blueprintId) {
        return datasets.findByBlueprintIdOrderByCreatedAtDesc(blueprintId).stream()
                .map(this::toDto)
                .toList();
    }

    @GetMapping("/datasets/{id}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable String id) {
        return datasets.findById(id)
                .map(entity -> ResponseEntity.ok(toDto(entity)))
                .orElse(ResponseEntity.notFound().build());
    }

    /** Paginated row browsing over the canonical Parquet (FR-G.1). */
    @GetMapping("/datasets/{id}/rows")
    public ResponseEntity<Map<String, Object>> rows(
            @PathVariable String id,
            @org.springframework.web.bind.annotation.RequestParam String table,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "0") int offset,
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "50") int limit) {
        DatasetEntity dataset = datasets.findById(id).orElse(null);
        if (dataset == null) {
            return ResponseEntity.notFound().build();
        }
        if (dataset.getCanonicalDir() == null) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "dataset has no canonical data yet",
                                 "status", dataset.getStatus()));
        }
        return ResponseEntity.ok(engine.readRows(dataset.getCanonicalDir(), table, offset, limit));
    }

    public record ExportRequest(List<String> formats) {}

    /** Export the canonical dataset to files (the always-available sink, FR-G.4). */
    @PostMapping("/datasets/{id}/export")
    public ResponseEntity<Map<String, Object>> export(
            @PathVariable String id, @RequestBody ExportRequest request) {
        DatasetEntity dataset = datasets.findById(id).orElse(null);
        if (dataset == null) {
            return ResponseEntity.notFound().build();
        }
        if (!"ready".equals(dataset.getStatus()) || dataset.getCanonicalDir() == null) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "dataset is not ready for export",
                                 "status", dataset.getStatus()));
        }
        Map<String, Object> loadPlan = parse(dataset.getLoadPlanJson());
        Map<String, Object> result = engine.exportDataset(
                dataset.getCanonicalDir(), loadPlan,
                dataset.getCanonicalDir() + "/exports",
                request.formats() == null ? List.of("csv") : request.formats());
        return ResponseEntity.ok(result);
    }

    public record MaterializeRequest(String connection, String mode, Boolean confirm) {}

    /**
     * Materialize into a named DB connection. Direct-DB sinks are side-effecting and gated
     * behind EXPLICIT confirmation (FR-G.4): the request must carry {@code confirm: true}.
     */
    @PostMapping("/datasets/{id}/materialize")
    public ResponseEntity<Map<String, Object>> materialize(
            @PathVariable String id, @RequestBody MaterializeRequest request) {
        DatasetEntity dataset = datasets.findById(id).orElse(null);
        if (dataset == null) {
            return ResponseEntity.notFound().build();
        }
        if (!Boolean.TRUE.equals(request.confirm())) {
            return ResponseEntity.badRequest().body(Map.of(
                    "error", "writing to a database is side-effecting; set confirm=true (FR-G.4)"));
        }
        if (request.connection() == null || request.connection().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "connection is required"));
        }
        if (!"ready".equals(dataset.getStatus())) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "dataset is not ready", "status", dataset.getStatus()));
        }
        String mode = request.mode() == null ? "replace" : request.mode();
        String jobId = jobManager.submitMaterialization(dataset, request.connection(), mode);
        return ResponseEntity.accepted().body(Map.of("jobId", jobId, "datasetId", id));
    }

    public record TeardownRequest(String connection, Boolean confirm) {}

    /** Tear a materialization down (scoped, idempotent). Also gated: it deletes from their DB. */
    @PostMapping("/datasets/{id}/teardown")
    public ResponseEntity<Map<String, Object>> teardown(
            @PathVariable String id, @RequestBody TeardownRequest request) {
        DatasetEntity dataset = datasets.findById(id).orElse(null);
        if (dataset == null) {
            return ResponseEntity.notFound().build();
        }
        if (!Boolean.TRUE.equals(request.confirm())) {
            return ResponseEntity.badRequest().body(Map.of(
                    "error", "teardown deletes from a database; set confirm=true"));
        }
        String jobId = jobManager.submitTeardown(dataset, request.connection());
        return ResponseEntity.accepted().body(Map.of("jobId", jobId, "datasetId", id));
    }

    private Map<String, Object> parse(String jsonText) {
        try {
            return json.readValue(jsonText, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            throw new IllegalStateException("corrupt load plan JSON", e);
        }
    }

    private Map<String, Object> toDto(DatasetEntity entity) {
        Map<String, Object> dto = new java.util.LinkedHashMap<>();
        dto.put("id", entity.getId());
        dto.put("blueprintId", entity.getBlueprintId());
        dto.put("name", entity.getName());
        dto.put("status", entity.getStatus());
        dto.put("namespace", entity.getNamespace());
        dto.put("canonicalDir", entity.getCanonicalDir());
        dto.put("seed", entity.getSeed());
        dto.put("artifactsVersion", entity.getArtifactsVersion());
        dto.put("rowCounts", parseNullable(entity.getRowCountsJson()));
        dto.put("validationReport", parseNullable(entity.getValidationReportJson()));
        dto.put("materializations", parseNullable(entity.getMaterializationsJson()));
        dto.put("createdAt", entity.getCreatedAt());
        return dto;
    }

    private Object parseNullable(String jsonText) {
        if (jsonText == null) {
            return null;
        }
        try {
            return json.readValue(jsonText, new TypeReference<Object>() {});
        } catch (Exception e) {
            throw new IllegalStateException("corrupt JSON aggregate", e);
        }
    }
}
