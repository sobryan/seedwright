#!/usr/bin/env bash
# seedwright on-prem quickstart (ADR-0004): one command to build + run the whole stack.
#
#   ./quickstart.sh            build everything and start the stack
#   ./quickstart.sh stop       stop the stack
#   ./quickstart.sh status     show what's running
#
# Prereqs: Java 21+, Maven, uv (https://docs.astral.sh/uv), Node 20+ (build-time only).
# Optional: GitHub Copilot CLI (`npm i -g @github/copilot`, authenticated) to use
#           provider=copilot-cli as the authoring LLM — no other API keys needed.
#
# Configure datastore connections (credentials stay on the jdbc-mcp node) via env vars:
#   SEEDWRIGHT_CONNECTIONS_<NAME>_URL / _USERNAME / _PASSWORD
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

stop() {
  for name in server jdbc-mcp; do
    if [[ -f "$RUN_DIR/$name.pid" ]]; then
      pkill -P "$(cat "$RUN_DIR/$name.pid")" 2>/dev/null || true
      kill "$(cat "$RUN_DIR/$name.pid")" 2>/dev/null || true
      rm -f "$RUN_DIR/$name.pid"
      echo "stopped $name"
    fi
  done
  pkill -f "io.seedwright.server.SeedwrightServerApplication" 2>/dev/null || true
  pkill -f "io.seedwright.jdbcmcp.JdbcMcpApplication" 2>/dev/null || true
}

status() {
  curl -sf -o /dev/null http://localhost:8080/api/blueprints && echo "central server : UP  http://localhost:8080 (UI + REST + MCP at /mcp)" || echo "central server : down"
  curl -sf -o /dev/null -X POST http://localhost:8081/mcp -H 'Content-Type: application/json' -d '{}' 2>/dev/null; [[ $? -lt 7 ]] && echo "jdbc-mcp node  : UP  http://localhost:8081/mcp" || echo "jdbc-mcp node  : down"
}

case "${1:-start}" in
  stop)   stop; exit 0 ;;
  status) status; exit 0 ;;
  start)  ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

echo "==> checking prerequisites"
for cmd in java mvn uv node npm; do
  command -v "$cmd" >/dev/null || { echo "missing prerequisite: $cmd"; exit 1; }
done

echo "==> building the Python data-engine (uv)"
(cd "$ROOT/data-engine" && uv sync -q)

echo "==> building the UI (static export)"
(cd "$ROOT/ui" && npm install --silent && npm run build --silent)

echo "==> building the Java services"
(cd "$ROOT/jdbc-mcp" && mvn -q -B -DskipTests package)
(cd "$ROOT/server" && mvn -q -B -DskipTests package)

echo "==> starting jdbc-mcp (port 8081)"
(cd "$ROOT/jdbc-mcp" && nohup java -jar target/seedwright-jdbc-mcp-0.0.1.jar \
    > "$RUN_DIR/jdbc-mcp.log" 2>&1 & echo $! > "$RUN_DIR/jdbc-mcp.pid")

echo "==> starting the central server (port 8080)"
(cd "$ROOT/server" && nohup java -jar target/seedwright-server-0.0.1.jar \
    > "$RUN_DIR/server.log" 2>&1 & echo $! > "$RUN_DIR/server.pid")

printf "==> waiting for the stack"
for _ in $(seq 1 60); do
  curl -sf -o /dev/null http://localhost:8080/api/blueprints && break
  printf "."; sleep 2
done
echo

status
cat <<'EOF'

seedwright is up.
  UI        http://localhost:8080/
  REST      http://localhost:8080/api
  MCP       http://localhost:8080/mcp        (agents: Copilot CLI, Claude Code, ...)
  logs      .run/server.log  .run/jdbc-mcp.log

Copilot CLI as an agent driving seedwright — add to ~/.copilot/mcp-config.json:
  { "mcpServers": { "seedwright": { "type": "http", "url": "http://localhost:8080/mcp" } } }

Copilot CLI as the AUTHORING LLM — create blueprints with "provider": "copilot-cli"
(requires an authenticated `copilot` on this host; the heuristic provider needs nothing).
EOF
