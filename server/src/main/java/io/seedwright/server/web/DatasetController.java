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
    private final ObjectMapper json;

    public DatasetController(DatasetRepository datasets, DataEngine engine, ObjectMapper json) {
        this.datasets = datasets;
        this.engine = engine;
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
