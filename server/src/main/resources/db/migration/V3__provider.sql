-- Authoring provider per Blueprint (FR-H: model management). 'heuristic' (no LLM) or
-- 'copilot-cli' (GitHub Copilot CLI as the authoring model).
ALTER TABLE blueprint ADD COLUMN provider VARCHAR(64);
