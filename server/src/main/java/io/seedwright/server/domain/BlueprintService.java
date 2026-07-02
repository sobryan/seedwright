package io.seedwright.server.domain;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;

/** Blueprint creation shared by the REST controller and the product MCP tools. */
@Service
public class BlueprintService {

    private final BlueprintRepository blueprints;
    private final ObjectMapper json;

    public BlueprintService(BlueprintRepository blueprints, ObjectMapper json) {
        this.blueprints = blueprints;
        this.json = json;
    }

    public BlueprintEntity create(String name,
                                  String description,
                                  Map<String, Object> schema,
                                  List<Map<String, Object>> rules,
                                  Map<String, Object> foreignKeys,
                                  Map<String, Object> volumes,
                                  Long seed) {
        try {
            BlueprintEntity entity = new BlueprintEntity();
            entity.setId(UUID.randomUUID().toString());
            entity.setName(name);
            entity.setDescription(description);
            entity.setStatus("draft");
            entity.setSeed(seed == null ? 42L : seed);
            entity.setSchemaJson(json.writeValueAsString(schema));
            entity.setRulesJson(json.writeValueAsString(rules == null ? List.of() : rules));
            entity.setForeignKeysJson(foreignKeys == null ? null : json.writeValueAsString(foreignKeys));
            entity.setVolumesJson(volumes == null ? null : json.writeValueAsString(volumes));
            entity.setCreatedAt(Instant.now());
            entity.setUpdatedAt(Instant.now());
            return blueprints.save(entity);
        } catch (Exception e) {
            throw new IllegalArgumentException("unserializable blueprint component", e);
        }
    }
}
