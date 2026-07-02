package io.seedwright.server.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * A Dataset (spec §4): one materialized generation from a Blueprint. Pins the artifacts version
 * and seed for reproducibility; carries refs to the canonical Parquet dir + Load Plan; status is
 * never 'ready' unless generation AND validation succeeded (FR-E.4).
 */
@Entity
@Table(name = "dataset")
public class DatasetEntity {

    @Id
    private String id;

    @Column(name = "blueprint_id", nullable = false)
    private String blueprintId;

    private String name;

    @Column(nullable = false)
    private String status;

    @Column(nullable = false)
    private String namespace;

    @Column(name = "canonical_dir")
    private String canonicalDir;

    private Long seed;

    @Column(name = "artifacts_version")
    private String artifactsVersion;

    @Lob
    @Column(name = "row_counts_json")
    private String rowCountsJson;

    @Lob
    @Column(name = "load_plan_json")
    private String loadPlanJson;

    @Lob
    @Column(name = "validation_report_json")
    private String validationReportJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getBlueprintId() { return blueprintId; }
    public void setBlueprintId(String blueprintId) { this.blueprintId = blueprintId; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getNamespace() { return namespace; }
    public void setNamespace(String namespace) { this.namespace = namespace; }
    public String getCanonicalDir() { return canonicalDir; }
    public void setCanonicalDir(String canonicalDir) { this.canonicalDir = canonicalDir; }
    public Long getSeed() { return seed; }
    public void setSeed(Long seed) { this.seed = seed; }
    public String getArtifactsVersion() { return artifactsVersion; }
    public void setArtifactsVersion(String artifactsVersion) { this.artifactsVersion = artifactsVersion; }
    public String getRowCountsJson() { return rowCountsJson; }
    public void setRowCountsJson(String rowCountsJson) { this.rowCountsJson = rowCountsJson; }
    public String getLoadPlanJson() { return loadPlanJson; }
    public void setLoadPlanJson(String loadPlanJson) { this.loadPlanJson = loadPlanJson; }
    public String getValidationReportJson() { return validationReportJson; }
    public void setValidationReportJson(String validationReportJson) { this.validationReportJson = validationReportJson; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
