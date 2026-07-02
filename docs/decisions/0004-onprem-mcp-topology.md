# ADR 0004 — On-prem topology: central Spring server + two MCP servers + Next.js

**Date:** 2026-07-01
**Status:** Accepted (user-directed)
**Context:** The deployment question ("can a small shop run this without standing up a heavy external DB?") was investigated and answered: nothing in the built code requires one — Postgres is an optional *sink*, the canonical format is Parquet files, and the spec's §7 metadata-store choice is explicitly a recommendation. The user then fixed the runtime shape for the **on-prem first** release (cloud later).

## Decision

Four components, one box, "one JVM + a couple processes":

1. **Central server — Spring Boot (Java 21).** REST API (async jobs per FR-I.2), job orchestration (virtual threads), and the **metadata store: H2 in file mode**, chosen because it must *persist past sudden restarts* — H2's file mode is a durable, journaled store and Spring/Hibernate support it first-class (unlike SQLite). Configure for crash safety (file DB under `./data/`, no in-memory mode, `DB_CLOSE_ON_EXIT=FALSE`; rely on MVStore journaling). Persistence via **Spring Data JPA + Flyway**; document-shaped aggregates (schema, rules, artifacts, load plans, reports) stored as Jackson-serialized JSON in CLOB columns; promoted scalar columns (ids, status, versions, timestamps) for filtering. Postgres remains a later opt-in — H2 and Postgres both have first-class Hibernate dialects, so the swap is dialect + Flyway variant, not a rewrite.
2. **Python MCP server — `data-engine/`.** All "Python data things" behind MCP tools: `author_generator` (authoring loop; mock provider now, real LLM adapters later behind the existing `Provider` protocol), `generate_dataset` (deterministic execute → canonical Parquet + Load Plan), `validate_dataset` (data-tests against the canonical Parquet), `export_dataset` (canonical → CSV/JSONL/SQL — the file sink, FR-G.4), plus `load_postgres`/`teardown_postgres` wrapping the proven Python loader until the Java loader matures. **Transport: stdio**, spawned and supervised by the central server — no port, no auth surface, dies/restarts with its parent.
3. **Java JDBC Spring MCP server — `jdbc-mcp/`.** Schema **introspection** (`introspect_schema`, feeds Blueprint creation per FR-A) and **loading** (`load_dataset` via dialect DDL + generic batched-INSERT — privilege-safe and works across JDBC targets incl. DB2 later; `teardown_dataset`; `verify_materialization`). Mirrors the Python loader's proven safety invariants: `ds_` namespace scoping, injection-safe identifiers, ownership-marker guard, no unscoped DROP/DELETE, pre-commit row-count verification. **Transport: Streamable HTTP** — listens on a port (localhost on-prem); the central server dials in. This is deliberately the same "server dials into node" pattern as the future cloud relay node: moving this artifact next to a remote datastore later changes configuration, not code.
4. **Frontend — Next.js**, static export served by the central server (no runtime Node process in production).

## Consequences

- The earlier subprocess-per-job worker design is superseded by the MCP-server topology; the canonical Parquet + Load Plan seam is unchanged and remains the contract.
- Long-running MCP tool calls are wrapped by the central server's JobManager (a Job row + a virtual thread per call, progress via MCP notifications where available); the Dataset is marked `ready` only on success (FR-E.4).
- Cross-language duplication of canonical→SQL mapping (Python loader vs Java loader) is bounded by (a) starting the Java loader with generic batched INSERT + a small dialect type table, and (b) the plan to extract a shared, language-neutral mapping table + conformance vectors before adding DB2.
- Deferred to the cloud phase: remote relay deployment (mTLS, signed per-command tokens, egress lockdown), object-storage canonical delivery, Postgres metadata opt-in, packaging matrix.
