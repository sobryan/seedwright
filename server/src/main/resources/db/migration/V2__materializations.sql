-- Per-sink materialization records (spec FR-G: which sinks a Dataset landed in + status).
ALTER TABLE dataset ADD COLUMN materializations_json CLOB;
