#!/bin/bash
set -euo pipefail

# Destroy Diode node stack for a given region
# Usage: ./destroy-node.sh [region]
#
# Environment variables:
#   PROVIDER - "lightsail" (default) or "ec2"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGION="${1:-ap-southeast-1}"
PROVIDER="${PROVIDER:-lightsail}"

if [ "$PROVIDER" = "ec2" ]; then
  STACK_NAME="DiodeNodesEc2-${REGION}"
else
  STACK_NAME="DiodeNodes-${REGION}"
fi

echo "=== Destroying Diode Node Stack ==="
echo "Provider: ${PROVIDER}"
echo "Stack:    ${STACK_NAME}"
echo "Region:   ${REGION}"
echo ""

cd "$INFRA_DIR"

echo "Running cdk destroy..."
npx cdk destroy "$STACK_NAME" --force \
  -c region="${REGION}" \
  -c instanceCount="1" \
  -c nodeTokens="placeholder" \
  -c provider="${PROVIDER}"

echo ""
echo "CDK stack destroyed."
echo ""
echo "NOTE: Node records still exist in the backend database."
echo "      Delete them via the admin dashboard or API:"
echo "      DELETE ${BACKEND_URL:-https://api.diode.dev}/api/admin/nodes/<node_id>"
