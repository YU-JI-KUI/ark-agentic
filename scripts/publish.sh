#!/usr/bin/env bash
# publish.sh — Build and upload ark-agentic (core + CLI only)
#
# Published wheel contains ONLY:
#   ark_agentic/__init__.py, core/**, cli/**
# Excluded from wheel (internal test code):
#   ark_agentic/agents/insurance, ark_agentic/agents/securities,
#   ark_agentic/app.py, ark_agentic/plugins/playground/static/**
#
# Usage:
#   ./scripts/publish.sh              # build + upload
#   ./scripts/publish.sh --dry-run    # build only, skip upload
#
# Env:
#   PYPI_REPO_URL   — upload endpoint (default: internal maven-pypi)
#   TWINE_USERNAME  — PyPI username
#   TWINE_PASSWORD  — PyPI password/token

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INTERNAL_REPO_URL="${PYPI_REPO_URL:-http://maven.abc.com.cn/repository/pypi/}"
DIST_DIR="$REPO_ROOT/dist"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

# Clean previous builds
rm -rf "$DIST_DIR"

# Read version
VERSION=$(python3 -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('$REPO_ROOT/pyproject.toml').read_text())
print(d['project']['version'])
")
echo "==> Version: $VERSION"

# 1) Build Studio frontend (dist/ force-included in wheel via pyproject.toml)
FRONTEND_DIR="$REPO_ROOT/src/ark_agentic/plugins/studio/frontend"
if [ -f "$FRONTEND_DIR/package.json" ]; then
  echo "==> Building Studio frontend..."
  cd "$FRONTEND_DIR"
  npm ci --ignore-scripts
  npm run build
  cd "$REPO_ROOT"
  echo "==> Studio frontend built"
fi

# 2) Build ark-agentic wheel
echo "==> Building ark-agentic..."
cd "$REPO_ROOT"
uv build --out-dir "$DIST_DIR"

echo ""
echo "==> Build artifacts:"
ls -lh "$DIST_DIR"

if [ "$DRY_RUN" = true ]; then
  echo "==> Dry run — skipping upload"
  exit 0
fi

# Upload to internal PyPI
echo "==> Uploading to $INTERNAL_REPO_URL ..."
cd "$REPO_ROOT"
twine upload \
  --repository-url "$INTERNAL_REPO_URL" \
  "$DIST_DIR"/ark_agentic-"$VERSION"*

echo "==> Published ark-agentic==$VERSION"
