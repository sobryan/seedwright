# seedwright central server

The one Java application at the center of the on-prem topology (ADR-0004): REST API + async
jobs + **H2 file-mode metadata that persists past sudden restarts** + MCP client to the Python
data-engine (spawned over stdio) and, later, the JDBC loader MCP server (HTTP).

```
POST /api/blueprints                     create a Blueprint (schema + rules + volumes + seed)
GET  /api/blueprints[/{id}]              read
POST /api/blueprints/{id}/datasets       trigger generation -> 202 + { jobId, datasetId }
GET  /api/jobs/{id}                      poll job status/progress
GET  /api/datasets/{id}                  dataset status, row counts, validation report
POST /api/datasets/{id}/export           canonical -> CSV/JSONL/SQL files
```

The generation flow per job (virtual thread, bounded concurrency): author-if-needed (artifacts
cached on the Blueprint) → generate (canonical Parquet + Load Plan on disk) → validate → dataset
`ready`/`quarantined` — never a silent partial (FR-E.4). Jobs orphaned by a sudden restart are
reconciled to `failed` on startup; a retry is a deterministic re-run.

## Run

Requires Java 21 + Maven, and `uv` (to spawn the Python data-engine — configure via
`seedwright.data-engine.*`).

```bash
cd server
mvn spring-boot:run          # metadata at ./data/seedwright.mv.db, datasets at ./data/datasets
mvn test                     # includes a LIVE Java<->Python stdio MCP test (skips without uv)
```
