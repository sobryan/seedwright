-- Artifact approval (FR-L.5): human approval of the authored Generator Artifacts is required
-- before a Dataset built from them may be materialized into a real database. Reset to
-- pending_approval whenever artifacts are (re)authored.
ALTER TABLE blueprint ADD COLUMN artifacts_approval VARCHAR(32);
ALTER TABLE blueprint ADD COLUMN artifacts_approved_by VARCHAR(255);
ALTER TABLE blueprint ADD COLUMN artifacts_approved_at TIMESTAMP(9) WITH TIME ZONE;
