# seedwright × GitHub Copilot CLI

Two independent integrations, usable together:

1. **Copilot CLI as an agent driving seedwright** — seedwright is an MCP server; Copilot calls
   its tools (below).
2. **Copilot CLI as the authoring LLM** — seedwright's evaluator-optimizer uses `copilot -p`
   headless as its model. Create Blueprints with `"provider": "copilot-cli"` (UI, REST, or the
   MCP tool). The shop's existing Copilot subscription is the model: **no new API keys, no new
   vendor**. The loop validates/judges every proposal against the schema and rules, feeds
   failures back for refinement, and never accepts a generator that fails its data-tests or the
   determinism gate — so model quality affects iteration count, never correctness. The default
   `heuristic` provider needs no LLM at all.

Requirements for (2): an authenticated `copilot` on the central-server host (run
`copilot` once interactively, or set `GH_TOKEN`).

# Using seedwright from GitHub Copilot CLI (integration 1)

seedwright's central server exposes its full product surface as an **MCP server** at
`http://<server>:8080/mcp` (Streamable HTTP). GitHub Copilot CLI speaks MCP natively, so a
developer can drive the on-prem install conversationally from the terminal:

> *"Introspect the `warehouse` connection, create a blueprint for the customers and orders
> tables with ~1000 customers, generate a dataset, and load it into `warehouse` — ask me before
> writing anything."*

## Setup

1. Run seedwright on-prem (central server on :8080; jdbc-mcp on :8081 with your named
   connections configured — see `jdbc-mcp/src/main/resources/application.yml`).
2. Register seedwright in Copilot CLI. Either use the interactive `/mcp add` command inside
   `copilot`, or add it to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "seedwright": {
      "type": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

3. Start `copilot` and check `/mcp` shows the seedwright server with its tools.

## The tool surface

| Tool | What it does |
|---|---|
| `list_connections` | Named datastore connections on the jdbc-mcp node (names only — credentials never leave that node) |
| `introspect_connection` | Read a DB's tables/columns/PKs/FKs — output plugs straight into `create_blueprint` |
| `create_blueprint` / `list_blueprints` | Define/inspect generation specs |
| `generate_dataset` | Author (no LLM needed — deterministic heuristic provider) + generate + validate; waits for completion |
| `get_job`, `list_datasets`, `get_dataset` | Track async work and results |
| `export_dataset` | Canonical data → CSV / JSONL / SQL files |
| `materialize_dataset` | Load into a named DB connection — **side-effecting and refused without `confirm=true`**; the tool description instructs the agent to ask you first (spec FR-G.4) |
| `teardown_dataset` | Remove a materialization (drops only its isolated `ds_` schema, ownership-marker-guarded) |

## Safety model for agents

- **Writes are double-gated**: Copilot CLI's own tool-approval prompt *and* seedwright's
  `confirm=true` requirement. An agent cannot write to a database silently.
- **Everything lands in an isolated `ds_<uuid>` schema** with an ownership marker; teardown can
  only ever drop seedwright-created schemas.
- **Reproducible by construction**: same blueprint + seed ⇒ identical data, so an agent
  re-running a job is safe and deterministic.
- Credentials live only in the jdbc-mcp node's config, never in the central server, the agent,
  or the conversation.

## Other MCP clients

The endpoint is standard MCP over Streamable HTTP, so the same URL works from Claude Code
(`claude mcp add --transport http seedwright http://localhost:8080/mcp`), VS Code, Cursor, or
any MCP-capable client.
