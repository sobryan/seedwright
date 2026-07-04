# seedwright — on-prem bundle

Model-agnostic synthetic data generation, self-contained. This bundle runs the whole stack
on one host with **no build tools and no separate database** — H2 file-mode metadata lives in
`./data` and survives sudden restarts.

## Prerequisites

- **Java 21+** — `java -version`
- **uv** — https://docs.astral.sh/uv (a single static binary; provides Python 3.12 and the
  data-engine's dependencies on first start, then caches them)

That's it. Maven, Node, and npm are **build-host only** — you don't need them here.

Optional authoring models (the default `heuristic` provider needs neither):
- `provider=copilot-cli` — GitHub Copilot CLI (`copilot`, authenticated) as the authoring LLM.
- `provider=anthropic` — the Anthropic API; set `ANTHROPIC_API_KEY` in the environment before
  `./bin/seedwright start` (the server passes it through to the generation engine).

Whichever model authors the generator, **execution is identical and model-free** — the same
seed always yields byte-identical data.

## Run

```bash
./bin/seedwright start     # start the stack (first run resolves Python deps)
./bin/seedwright status    # what's up
./bin/seedwright stop      # stop it
```

Then open **http://localhost:8080/** — create a Blueprint (the form is prefilled with a working
demo), generate a Dataset, preview and browse rows, export to files. Set `SEEDWRIGHT_SERVER_PORT`
to move it off 8080.

## Connect your databases (optional)

Loading generated data into a real database is **opt-in and gated** (you confirm each write;
the generator artifacts must be human-approved first). Credentials stay on the JDBC loader
node — the central server and any model only ever see connection *names*.

1. Edit `conf/jdbc-mcp.yml` — add your targets under `seedwright.connections` (use a
   least-privilege role: it needs to create/drop only its own `ds_` schemas, never touch your
   real tables).
2. For dialects beyond Postgres/H2 (DB2, Oracle, …), drop the JDBC driver jar into `./drivers`.
3. Restart. The connection appears in the UI's load picker and over MCP.

## What's in the box

```
bin/seedwright                  launcher (start|stop|status)
lib/seedwright-server-*.jar     central server: REST + UI + MCP + H2 metadata
lib/seedwright-jdbc-mcp-*.jar   JDBC loader node (schema introspection + scoped load/teardown)
ui/                             the web UI (static — served by the server, no Node at runtime)
data-engine/                    the Python generation engine (source; uv resolves deps)
conf/application.yml            central server overrides (bundle-relative paths)
conf/jdbc-mcp.yml               your datastore connections (credentials live here)
drivers/                        drop-in JDBC driver jars
data/                           H2 metadata + canonical Parquet (created on first run)
```

## Agents

The server exposes its full product surface as MCP tools at `http://localhost:8080/mcp`
(Streamable HTTP). Point Copilot CLI, Claude Code, VS Code, or Cursor at it — writes to a
database still require explicit confirmation and approved artifacts.
