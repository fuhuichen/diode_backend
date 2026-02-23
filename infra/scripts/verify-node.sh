#!/bin/bash
set -euo pipefail

# Verify that deployed Diode nodes come online
# Usage: ./verify-node.sh <region> <expected_count> <backend_url> <jwt>

REGION="${1:?Usage: verify-node.sh <region> <count> <backend_url> <jwt>}"
EXPECTED_COUNT="${2:?Expected node count required}"
BACKEND_URL="${3:?Backend URL required}"
JWT="${4:?JWT token required}"

TIMEOUT=180
INTERVAL=15
ELAPSED=0

echo "Verifying ${EXPECTED_COUNT} node(s) in region '${REGION}'..."
echo "Timeout: ${TIMEOUT}s, polling every ${INTERVAL}s"

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  NODES_RESP=$(curl -sf "${BACKEND_URL}/api/admin/nodes" \
    -H "Authorization: Bearer ${JWT}" || echo "[]")

  # Count online nodes in this region with a client_address
  ONLINE_COUNT=$(echo "$NODES_RESP" | python3 -c "
import sys, json
nodes = json.load(sys.stdin)
count = sum(
    1 for n in nodes
    if n.get('region') == '${REGION}'
    and n.get('status') == 'online'
    and n.get('client_address')
)
print(count)
" 2>/dev/null || echo "0")

  echo "  [${ELAPSED}s] Online nodes in ${REGION}: ${ONLINE_COUNT}/${EXPECTED_COUNT}"

  if [ "$ONLINE_COUNT" -ge "$EXPECTED_COUNT" ]; then
    echo "All ${EXPECTED_COUNT} node(s) are online!"
    # Print node details
    echo "$NODES_RESP" | python3 -c "
import sys, json
nodes = json.load(sys.stdin)
for n in nodes:
    if n.get('region') == '${REGION}' and n.get('status') == 'online':
        print(f\"  - {n['name']}: {n['client_address']} (status: {n['status']})\")
"
    exit 0
  fi

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo "ERROR: Timed out after ${TIMEOUT}s. Only ${ONLINE_COUNT}/${EXPECTED_COUNT} nodes online."
echo "Check instance logs: SSH in and view /var/log/diode-setup.log"
exit 1
