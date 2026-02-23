#!/bin/bash
set -euo pipefail

# Deploy Diode nodes to AWS Lightsail via CDK
# Usage: ./deploy-node.sh [region] [count]
#
# Environment variables:
#   ADMIN_USERNAME - Admin username for backend login (default: admin)
#   ADMIN_PASSWORD - Admin password for backend login
#   BACKEND_URL    - Backend API URL (default: https://api.diode.dev)
#   DIODE_VERSION  - Diode client version (default: v1.17.2)
#   BUNDLE_ID      - Lightsail bundle (default: nano_3_0)
#   KEY_PAIR_NAME  - Optional Lightsail key pair for SSH access

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REGION="${1:-ap-southeast-1}"
COUNT="${2:-1}"

BACKEND_URL="${BACKEND_URL:-http://13.213.186.48/diode}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
DIODE_VERSION="${DIODE_VERSION:-v1.17.2}"
BUNDLE_ID="${BUNDLE_ID:-nano_3_0}"
KEY_PAIR_NAME="${KEY_PAIR_NAME:-}"

echo "=== Diode Node Deployment ==="
echo "Region:  ${REGION}"
echo "Count:   ${COUNT}"
echo "Backend: ${BACKEND_URL}"
echo "Version: ${DIODE_VERSION}"
echo "Bundle:  ${BUNDLE_ID}"
echo ""

# --- 1. Authenticate with backend ---
if [ -z "${ADMIN_PASSWORD:-}" ]; then
  echo -n "Admin password: "
  read -rs ADMIN_PASSWORD
  echo ""
fi

echo "Authenticating with backend..."
LOGIN_RESP=$(curl -sf "${BACKEND_URL}/api/admin/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"${ADMIN_USERNAME}\", \"password\": \"${ADMIN_PASSWORD}\"}")

JWT=$(echo "$LOGIN_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
echo "Authenticated successfully."

# --- 2. Create nodes via admin API ---
echo "Creating ${COUNT} node(s) in region '${REGION}'..."
NODE_TOKENS=""

for i in $(seq 0 $((COUNT - 1))); do
  NODE_NAME="diode-node-${REGION}-${i}"
  CREATE_RESP=$(curl -sf "${BACKEND_URL}/api/admin/nodes" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${JWT}" \
    -d "{\"name\": \"${NODE_NAME}\", \"region\": \"${REGION}\"}")

  TOKEN=$(echo "$CREATE_RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['node_token'])")
  echo "  Created node: ${NODE_NAME} (token: ${TOKEN:0:10}...)"

  if [ -n "$NODE_TOKENS" ]; then
    NODE_TOKENS="${NODE_TOKENS},${TOKEN}"
  else
    NODE_TOKENS="${TOKEN}"
  fi
done

# --- 3. CDK Deploy ---
echo ""
echo "Deploying CDK stack DiodeNodes-${REGION}..."
cd "$INFRA_DIR"

npx cdk deploy "DiodeNodes-${REGION}" \
  --require-approval never \
  -c region="${REGION}" \
  -c instanceCount="${COUNT}" \
  -c nodeTokens="${NODE_TOKENS}" \
  -c bundleId="${BUNDLE_ID}" \
  -c diodeVersion="${DIODE_VERSION}" \
  -c backendUrl="${BACKEND_URL}" \
  -c keyPairName="${KEY_PAIR_NAME}"

echo ""
echo "CDK deployment complete."

# --- 4. Verify nodes come online ---
echo ""
echo "Waiting for nodes to come online..."
"$SCRIPT_DIR/verify-node.sh" "${REGION}" "${COUNT}" "${BACKEND_URL}" "${JWT}"

echo ""
echo "=== Deployment Complete ==="
