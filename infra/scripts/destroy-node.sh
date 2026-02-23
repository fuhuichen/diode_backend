#!/bin/bash
set -euo pipefail

# Destroy Diode node stack for a given region
# Usage: ./destroy-node.sh [region]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGION="${1:-ap-southeast-1}"
STACK_NAME="DiodeNodes-${REGION}"

echo "=== Destroying Diode Node Stack ==="
echo "Stack:  ${STACK_NAME}"
echo "Region: ${REGION}"
echo ""

cd "$INFRA_DIR"

echo "Running cdk destroy..."
npx cdk destroy "$STACK_NAME" --force \
  -c region="${REGION}" \
  -c instanceCount="1" \
  -c nodeTokens="placeholder"

echo ""
echo "CDK stack destroyed."
echo ""
echo "NOTE: Node records still exist in the backend database."
echo "      Delete them via the admin dashboard or API:"
echo "      DELETE ${BACKEND_URL:-https://api.diode.dev}/api/admin/nodes/<node_id>"
