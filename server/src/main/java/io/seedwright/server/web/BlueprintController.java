package io.seedwright.server.web;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.seedwright.server.domain.BlueprintEntity;
import io.seedwright.server.domain.BlueprintRepository;
import io.seedwright.server.jobs.JobManager;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/blueprints")
public class BlueprintController {

    private final BlueprintRepository blueprints;
    private final io.seedwright.server.domain.BlueprintService blueprintService;
    private final JobManager jobManager;
    private final ObjectMapper json;

    public BlueprintController(BlueprintRepository blueprints,
                               io.seedwright.server.domain.BlueprintService blueprintService,
                               JobManager jobManager, ObjectMapper json) {
        this.blueprints = blueprints;
        this.blueprintService = blueprintService;
        this.jobManager = jobManager;
        this.json = json;
    }

    public record CreateBlueprintRequest(
            @NotBlank String name,
            String description,
            @NotNull Map<String, Object> schema,
            List<Map<String, Object>> rules,
            Map<String, Object> foreignKeys,
            Map<String, Object> volumes,
            Long seed,
            String provider) {}

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(
            @RequestBody @jakarta.validation.Valid CreateBlueprintRequest request) {
        BlueprintEntity entity = blueprintService.create(
                request.name(), request.description(), request.schema(), request.rules(),
                request.foreignKeys(), request.volumes(), request.seed(), request.provider());
        return ResponseEntity.created(URI.create("/api/blueprints/" + entity.getId())).body(toDto(entity));
    }

    @GetMapping
    public List<Map<String, Object>> list() {
        return blueprints.findAll().stream().map(this::toDto).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable String id) {
        return blueprints.findById(id)
                .map(entity -> ResponseEntity.ok(toDto(entity)))
                .orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable String id) {
        if (!blueprints.existsById(id)) {
            return ResponseEntity.notFound().build();
        }
        blueprints.deleteById(id);
        return ResponseEntity.noContent().build();
    }

    public record TriggerGenerationRequest(String datasetName) {}

    /** Trigger generation (FR-I.2): 202 Accepted + a Job to poll. */
    @PostMapping("/{id}/datasets")
    public ResponseEntity<Map<String, Object>> generate(
            @PathVariable String id, @RequestBody(required = false) TriggerGenerationRequest request) {
        return blueprints.findById(id)
                .map(blueprint -> {
                    var handles = jobManager.submitGeneration(
                            blueprint, request == null ? null : request.datasetName());
                    return ResponseEntity.accepted()
                            .location(URI.create("/api/jobs/" + handles.jobId()))
                            .body(Map.<String, Object>of(
                                    "jobId", handles.jobId(),
                                    "datasetId", handles.datasetId()));
                })
                .orElse(ResponseEntity.notFound().build());
    }

    private Map<String, Object> toDto(BlueprintEntity entity) {
        Map<String, Object> dto = new java.util.LinkedHashMap<>();
        dto.put("id", entity.getId());
        dto.put("name", entity.getName());
        dto.put("description", entity.getDescription());
        dto.put("status", entity.getStatus());
        dto.put("seed", entity.getSeed());
        dto.put("schema", parse(entity.getSchemaJson()));
        dto.put("rules", parse(entity.getRulesJson()));
        dto.put("foreignKeys", parse(entity.getForeignKeysJson()));
        dto.put("volumes", parse(entity.getVolumesJson()));
        dto.put("artifactsVersion", entity.getArtifactsVersion());
        dto.put("provider", entity.getProvider());
        dto.put("createdAt", entity.getCreatedAt());
        dto.put("updatedAt", entity.getUpdatedAt());
        return dto;
    }

    private Object parse(String jsonText) {
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
