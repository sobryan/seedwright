-- seedwright metadata schema (H2 file mode; Flyway owns DDL — spec §4 domain model, thin
-- relational spine + JSON aggregates as CLOBs).

CREATE TABLE blueprint (
    id                 VARCHAR(64)  PRIMARY KEY,
    name               VARCHAR(255) NOT NULL,
    description        VARCHAR(1024),
    status             VARCHAR(32)  NOT NULL,
    seed               BIGINT       NOT NULL,
    schema_json        CLOB         NOT NULL,
    rules_json         CLOB,
    foreign_keys_json  CLOB,
    volumes_json       CLOB,
    artifacts_json     CLOB,
    artifacts_version  VARCHAR(64),
    created_at         TIMESTAMP(9) WITH TIME ZONE NOT NULL,
    updated_at         TIMESTAMP(9) WITH TIME ZONE NOT NULL
);

CREATE TABLE dataset (
    id                      VARCHAR(64)  PRIMARY KEY,
    blueprint_id            VARCHAR(64)  NOT NULL,
    name                    VARCHAR(255),
    status                  VARCHAR(32)  NOT NULL,
    namespace               VARCHAR(63)  NOT NULL,
    canonical_dir           VARCHAR(1024),
    seed                    BIGINT,
    artifacts_version       VARCHAR(64),
    row_counts_json         CLOB,
    load_plan_json          CLOB,
    validation_report_json  CLOB,
    created_at              TIMESTAMP(9) WITH TIME ZONE NOT NULL
);
CREATE INDEX idx_dataset_blueprint ON dataset(blueprint_id);

CREATE TABLE job (
    id           VARCHAR(64) PRIMARY KEY,
    type         VARCHAR(32) NOT NULL,
    status       VARCHAR(32) NOT NULL,
    blueprint_id VARCHAR(64),
    dataset_id   VARCHAR(64),
    message      VARCHAR(2048),
    error        CLOB,
    created_at   TIMESTAMP(9) WITH TIME ZONE NOT NULL,
    started_at   TIMESTAMP(9) WITH TIME ZONE,
    finished_at  TIMESTAMP(9) WITH TIME ZONE
);
CREATE INDEX idx_job_status ON job(status);
CREATE INDEX idx_job_dataset ON job(dataset_id);
