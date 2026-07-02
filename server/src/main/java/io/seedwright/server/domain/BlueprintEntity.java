package io.seedwright.server.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * A Blueprint (spec §4): the versioned generation spec. Thin relational spine (promoted scalar
 * columns for filtering) + JSON aggregates (schema, rules, FK topology, volumes, the authored
 * Generator Artifacts) stored as CLOBs — the app reads/writes them whole by id.
 */
@Entity
@Table(name = "blueprint")
public class BlueprintEntity {

    @Id
    private String id;

    @Column(nullable = false)
    private String name;

    private String description;

    @Column(nullable = false)
    private String status;

    @Column(nullable = false)
    private long seed;

    @Lob
    @Column(name = "schema_json", nullable = false)
    private String schemaJson;

    @Lob
    @Column(name = "rules_json")
    private String rulesJson;

    @Lob
    @Column(name = "foreign_keys_json")
    private String foreignKeysJson;

    @Lob
    @Column(name = "volumes_json")
    private String volumesJson;

    @Lob
    @Column(name = "artifacts_json")
    private String artifactsJson;

    @Column(name = "artifacts_version")
    private String artifactsVersion;

    /** Authoring provider: 'heuristic' (default, no LLM) or 'copilot-cli'. */
    private String provider;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public long getSeed() { return seed; }
    public void setSeed(long seed) { this.seed = seed; }
    public String getSchemaJson() { return schemaJson; }
    public void setSchemaJson(String schemaJson) { this.schemaJson = schemaJson; }
    public String getRulesJson() { return rulesJson; }
    public void setRulesJson(String rulesJson) { this.rulesJson = rulesJson; }
    public String getForeignKeysJson() { return foreignKeysJson; }
    public void setForeignKeysJson(String foreignKeysJson) { this.foreignKeysJson = foreignKeysJson; }
    public String getVolumesJson() { return volumesJson; }
    public void setVolumesJson(String volumesJson) { this.volumesJson = volumesJson; }
    public String getArtifactsJson() { return artifactsJson; }
    public void setArtifactsJson(String artifactsJson) { this.artifactsJson = artifactsJson; }
    public String getArtifactsVersion() { return artifactsVersion; }
    public void setArtifactsVersion(String artifactsVersion) { this.artifactsVersion = artifactsVersion; }
    public String getProvider() { return provider; }
    public void setProvider(String provider) { this.provider = provider; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
}
