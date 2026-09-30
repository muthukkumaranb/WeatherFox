#!/usr/bin/env bash
# edge_measure.sh — run on Linux/Codespaces with gcc available
# Generates tiny_tree.c from a fitted sklearn tree,
# then measures parity and performance against the Python rule_gate.
#
# Usage:
#   bash scripts/edge_measure.sh
#
# Requirements:
#   - gcc (any version)
#   - Python 3.9+ with skyguard dependencies installed
#   - Run from the repo root

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python}"

echo "=== SkyGuard Edge Measure ==="
echo "Repo root: $REPO_ROOT"
echo "Python: $($PYTHON --version)"
echo ""

# Step 1: Generate tiny_tree.c from fitted sklearn tree
echo "[1/2] Running export.py to train and generate tiny_tree.c ..."
cd "$REPO_ROOT"
$PYTHON skyguard/edge/export.py

if [[ ! -f "skyguard/edge/c/tiny_tree.c" ]]; then
    echo "ERROR: tiny_tree.c not found after export.py"
    exit 1
fi
echo "  Generated: skyguard/edge/c/tiny_tree.c"
echo ""

# Step 2: Build and measure with build_host.py
echo "[2/2] Running build_host.py to compile, measure parity and performance ..."
$PYTHON skyguard/edge/build_host.py

if [[ -f "reports/edge/edge.json" ]]; then
    echo ""
    echo "=== edge.json ==="
    cat reports/edge/edge.json
else
    echo "WARNING: reports/edge/edge.json not produced"
fi

echo ""
echo "Done. edge.json written to reports/edge/edge.json"
