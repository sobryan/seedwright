#!/usr/bin/env bash
# seedwright — build a relocatable on-prem bundle (ADR-0004, non-Docker packaging).
#
#   ./package.sh                 build from source, produce dist/seedwright-<version>.tar.gz
#   ./package.sh --no-build      skip the build, package already-built artifacts
#
# The tarball needs only Java 21 + uv at the target (no Maven/Node/npm). It ships:
#   the two service jars, the UI static export, the data-engine source, bundle-relative
#   config, a launcher, and a README. See packaging/ for the templated pieces.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# the PROJECT version — the <version> that follows the project artifactId, not the parent's
VERSION="$(grep -A1 'seedwright-server</artifactId>' "$ROOT/server/pom.xml" \
  | grep '<version>' | sed -E 's/.*<version>(.*)<\/version>.*/\1/')"
STAGE="$ROOT/dist/seedwright-$VERSION"
TARBALL="$ROOT/dist/seedwright-$VERSION.tar.gz"

BUILD=1
[[ "${1:-}" == "--no-build" ]] && BUILD=0

if [[ $BUILD -eq 1 ]]; then
  echo "==> checking build prerequisites"
  for cmd in java mvn uv node npm; do
    command -v "$cmd" >/dev/null || { echo "missing build prerequisite: $cmd"; exit 1; }
  done
  echo "==> building the UI (static export)"
  (cd "$ROOT/ui" && npm install --silent && npm run build --silent)
  echo "==> building the service jars"
  (cd "$ROOT/jdbc-mcp" && mvn -q -B -DskipTests package)
  (cd "$ROOT/server"   && mvn -q -B -DskipTests package)
fi

echo "==> assembling $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/lib" "$STAGE/ui" "$STAGE/data-engine" "$STAGE/conf" "$STAGE/bin" "$STAGE/drivers"

# service jars
cp "$ROOT"/server/target/seedwright-server-*.jar     "$STAGE/lib/"
cp "$ROOT"/jdbc-mcp/target/seedwright-jdbc-mcp-*.jar  "$STAGE/lib/"

# UI static export
cp -R "$ROOT"/ui/out/. "$STAGE/ui/"

# Ship the Python projects as source (deps resolved by uv at the target — NOT a pre-built
# venv, which hardcodes absolute paths + platform and wouldn't relocate). The data-engine
# path-depends on genlib/authoring/pgloader via "../<name>", so they must sit as SIBLINGS of
# data-engine in the bundle for uv to resolve them exactly as in-tree.
copy_pyproject() {  # <src-dir> <dest-dir>
  local src="$1" dest="$2"
  mkdir -p "$dest"
  for item in pyproject.toml uv.lock README.md src; do
    [[ -e "$src/$item" ]] && cp -R "$src/$item" "$dest/"
  done
}
copy_pyproject "$ROOT/data-engine"        "$STAGE/data-engine"
copy_pyproject "$ROOT/generation-library" "$STAGE/generation-library"
copy_pyproject "$ROOT/authoring"          "$STAGE/authoring"
copy_pyproject "$ROOT/postgres-loader"    "$STAGE/postgres-loader"

# launcher + config templates + docs
cp "$ROOT/packaging/bin/seedwright"        "$STAGE/bin/seedwright"
cp "$ROOT/packaging/conf/application.yml"  "$STAGE/conf/application.yml"
cp "$ROOT/packaging/conf/jdbc-mcp.yml"     "$STAGE/conf/jdbc-mcp.yml"
cp "$ROOT/packaging/README.md"             "$STAGE/README.md"
cp "$ROOT/packaging/drivers/README.md"     "$STAGE/drivers/README.md"
cp "$ROOT/LICENSE"                          "$STAGE/LICENSE"
echo "$VERSION" > "$STAGE/VERSION"
chmod +x "$STAGE/bin/seedwright"

echo "==> compressing"
(cd "$ROOT/dist" && tar -czf "$TARBALL" "seedwright-$VERSION")

echo
echo "built $TARBALL"
du -h "$TARBALL" | cut -f1 | sed 's/^/  size: /'
echo "  target prereqs: Java 21 + uv"
echo "  run: tar -xzf $(basename "$TARBALL") && cd seedwright-$VERSION && ./bin/seedwright start"
