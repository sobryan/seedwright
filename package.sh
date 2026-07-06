#!/usr/bin/env bash
# seedwright — build a relocatable on-prem bundle (ADR-0004, non-Docker packaging).
#
#   ./package.sh                 online bundle (Java 21 + uv at target; resolves Python deps
#                                on first start)
#   ./package.sh --offline       AIR-GAPPED bundle (Java 21 + Python 3.12 at target; ships a
#                                platform-specific wheelhouse, builds the data-engine venv with
#                                NO network). Tarball is tagged with the build platform — build
#                                on a host matching the target's OS/arch.
#   ./package.sh --no-build      skip the build, package already-built artifacts (online)
#   ./package.sh --offline --no-build
#
# Both ship the two service jars, the UI static export, bundle-relative config, a launcher, and
# a README. See packaging/ for the templated pieces.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# the PROJECT version — the <version> that follows the project artifactId, not the parent's
VERSION="$(grep -A1 'seedwright-server</artifactId>' "$ROOT/server/pom.xml" \
  | grep '<version>' | sed -E 's/.*<version>(.*)<\/version>.*/\1/')"

OFFLINE=0
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --offline)  OFFLINE=1 ;;
    --no-build) BUILD=0 ;;
    *) echo "unknown flag: $arg"; exit 1 ;;
  esac
done

if [[ $OFFLINE -eq 1 ]]; then
  PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)"
  NAME="seedwright-$VERSION-offline-$PLATFORM"
else
  NAME="seedwright-$VERSION"
fi
STAGE="$ROOT/dist/$NAME"
TARBALL="$ROOT/dist/$NAME.tar.gz"

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
mkdir -p "$STAGE/lib" "$STAGE/ui" "$STAGE/conf" "$STAGE/bin" "$STAGE/drivers"

# service jars (self-contained Spring Boot uberjars — no network at runtime either way)
cp "$ROOT"/server/target/seedwright-server-*.jar     "$STAGE/lib/"
cp "$ROOT"/jdbc-mcp/target/seedwright-jdbc-mcp-*.jar  "$STAGE/lib/"

# UI static export
cp -R "$ROOT"/ui/out/. "$STAGE/ui/"

if [[ $OFFLINE -eq 1 ]]; then
  # AIR-GAPPED: vendor a complete wheelhouse. The venv is built at the target with
  # `pip install --no-index --find-links wheelhouse`, so every dependency must be present
  # here as a wheel. Wheels are platform+arch+pyver specific (pyarrow/numpy ship binaries),
  # hence the platform tag. uv provides an ephemeral Python 3.12 + pip to download for 3.12.
  echo "==> building the wheelhouse (Python 3.12, platform $PLATFORM)"
  mkdir -p "$STAGE/wheelhouse"
  uv python install 3.12 >/dev/null 2>&1 || true
  # third-party closure: uv export lists the full locked set; the '==' lines are the
  # third-party pins (local projects appear as '-e ../…' and are built separately below).
  # --no-dev: runtime closure only (no pytest/mypy/ruff) — this is a production bundle
  reqs="$(mktemp)"
  (cd "$ROOT/data-engine" && uv export --no-hashes --no-dev --format requirements-txt) \
    | grep -E '^[A-Za-z0-9._-]+==' > "$reqs"
  uv run --python 3.12 --with pip -- \
    python -m pip download -r "$reqs" -d "$STAGE/wheelhouse" --only-binary=:all:
  rm -f "$reqs"
  # local projects -> wheels (their built metadata depends on the others by plain name, so
  # pip resolves them from the same wheelhouse offline)
  for proj in generation-library authoring postgres-loader data-engine; do
    (cd "$ROOT/$proj" && uv build --wheel -o "$STAGE/wheelhouse" >/dev/null)
  done
  cp "$ROOT/packaging/conf/application-offline.yml" "$STAGE/conf/application.yml"

  # --- bundle the runtimes so the air-gapped bundle needs NOTHING on the host ---
  mkdir -p "$STAGE/runtime"

  # CPython: uv's managed 3.12 is a python-build-standalone build (relocatable by design).
  echo "==> bundling CPython 3.12 (runtime/python)"
  uv python install 3.12 >/dev/null 2>&1 || true
  pybase=""
  for d in "$(uv python dir)"/cpython-3.12*-*; do
    [[ -L "$d" ]] && continue   # skip the version alias symlink; keep the real install dir
    pybase="$d"
  done
  [[ -n "$pybase" && -x "$pybase/bin/python3.12" ]] || { echo "could not locate a managed CPython 3.12"; exit 1; }
  cp -R "$pybase" "$STAGE/runtime/python"

  # Java: a jlink slim image when the build JDK ships jmods; otherwise copy the runtime image
  # wholesale (a JRE/JBR is relocatable and runs the Spring jars). Same platform as the target.
  echo "==> bundling the Java runtime (runtime/java)"
  jhome="$(java -XshowSettings:properties -version 2>&1 | sed -n 's/.*java.home = //p' | head -1)"
  [[ -n "$jhome" ]] || { echo "could not resolve java.home"; exit 1; }
  if [[ -d "$jhome/jmods" && -x "$jhome/bin/jlink" ]]; then
    "$jhome/bin/jlink" \
      --add-modules java.se,jdk.unsupported,jdk.crypto.ec,jdk.crypto.cryptoki,jdk.charsets,jdk.localedata,jdk.zipfs,jdk.management,jdk.naming.dns,jdk.httpserver,jdk.security.auth,jdk.security.jgss,jdk.net \
      --strip-debug --no-man-pages --no-header-files \
      --output "$STAGE/runtime/java"
  else
    echo "    (no jmods in the build JDK — copying the runtime image wholesale)"
    cp -R "$jhome" "$STAGE/runtime/java"
    chmod +x "$STAGE/runtime/java/bin/java" 2>/dev/null || true
  fi
else
  # ONLINE: ship the Python projects as source (deps resolved by uv at the target — NOT a
  # pre-built venv, which hardcodes absolute paths + platform and wouldn't relocate). The
  # data-engine path-depends on genlib/authoring/pgloader via "../<name>", so they sit as
  # SIBLINGS of data-engine in the bundle for uv to resolve them exactly as in-tree.
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
  cp "$ROOT/packaging/conf/application.yml" "$STAGE/conf/application.yml"
fi

# launcher + config templates + docs (shared)
cp "$ROOT/packaging/bin/seedwright"     "$STAGE/bin/seedwright"
cp "$ROOT/packaging/conf/jdbc-mcp.yml"  "$STAGE/conf/jdbc-mcp.yml"
cp "$ROOT/packaging/README.md"          "$STAGE/README.md"
cp "$ROOT/packaging/drivers/README.md"  "$STAGE/drivers/README.md"
cp "$ROOT/LICENSE"                       "$STAGE/LICENSE"
echo "$VERSION" > "$STAGE/VERSION"
chmod +x "$STAGE/bin/seedwright"

echo "==> compressing"
(cd "$ROOT/dist" && tar -czf "$TARBALL" "$NAME")

echo
echo "built $TARBALL"
du -h "$TARBALL" | cut -f1 | sed 's/^/  size: /'
if [[ $OFFLINE -eq 1 ]]; then
  echo "  target prereqs: NONE — Java + Python runtimes bundled (NO network, NO uv). Platform: $PLATFORM"
else
  echo "  target prereqs: Java 21 + uv"
fi
echo "  run: tar -xzf $(basename "$TARBALL") && cd $NAME && ./bin/seedwright start"
