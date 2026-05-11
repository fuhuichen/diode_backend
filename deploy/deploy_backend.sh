#!/usr/bin/env bash
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────
REMOTE_USER="ubuntu"
REMOTE_HOST="13.213.186.48"
REMOTE_DIR="/mnt/data/diode_backend"
SSH_KEY="${SSH_KEY:-$HOME/work/certs/BillingKey.pem}"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new"
SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Diode Backend Deployment ==="
echo "Target: ${SSH_TARGET}:${REMOTE_DIR}"
echo "Source: ${PROJECT_DIR}"
echo ""

# ── Step 1: Rsync project files ────────────────────────────────
echo "[1/6] Syncing files to remote..."
ssh ${SSH_OPTS} "${SSH_TARGET}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_DIR}"
rsync -avz --delete -e "ssh ${SSH_OPTS}" \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'deploy/' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude 'infra/node_modules' \
    --exclude 'infra/cdk.out' \
    "${PROJECT_DIR}/" "${SSH_TARGET}:${REMOTE_DIR}/"

# Copy production docker-compose and .env
scp ${SSH_OPTS} "${SCRIPT_DIR}/docker-compose.production.yml" "${SSH_TARGET}:${REMOTE_DIR}/docker-compose.yml"
scp ${SSH_OPTS} "${SCRIPT_DIR}/.env.production" "${SSH_TARGET}:${REMOTE_DIR}/.env"
echo "   Files synced."

# ── Step 2: Docker Compose build & up ──────────────────────────
echo "[2/6] Building and starting Docker containers..."
ssh ${SSH_OPTS} "${SSH_TARGET}" "cd ${REMOTE_DIR} && sudo docker compose up -d --build"
echo "   Containers started."

# ── Step 3: Wait for PostgreSQL to be ready ────────────────────
echo "[3/6] Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if ssh ${SSH_OPTS} "${SSH_TARGET}" "sudo docker compose -f ${REMOTE_DIR}/docker-compose.yml exec -T db pg_isready -U diode -d diode_backend" &>/dev/null; then
        echo "   PostgreSQL is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "   ERROR: PostgreSQL did not become ready in time."
        exit 1
    fi
    sleep 2
done

# ── Step 4: Initialize database ────────────────────────────────
echo "[4/6] Initializing database tables..."
ssh ${SSH_OPTS} "${SSH_TARGET}" "cd ${REMOTE_DIR} && sudo docker compose exec -T backend python -m init_db"
echo "   Database initialized."

# ── Step 5: Configure nginx (conf.d) ─────────────────────────────
echo "[5/6] Configuring nginx..."

ssh ${SSH_OPTS} "${SSH_TARGET}" "
cat <<'NGINX_EOF' | sudo tee /etc/nginx/conf.d/diode.conf > /dev/null
server {
    listen 80;
    server_name _;
    location /diode/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
    }
}
NGINX_EOF
"

echo "   Testing nginx configuration..."
if ssh ${SSH_OPTS} "${SSH_TARGET}" "sudo nginx -t" 2>&1; then
    ssh ${SSH_OPTS} "${SSH_TARGET}" "sudo systemctl reload nginx"
    echo "   Nginx reloaded."
else
    echo "   ERROR: nginx config test failed!"
    exit 1
fi

# ── Step 6: Verify deployment ──────────────────────────────────
echo "[6/6] Verifying deployment..."
echo ""

PASS=0
FAIL=0

# Check Docker containers
echo -n "   Docker containers running: "
CONTAINERS=$(ssh ${SSH_OPTS} "${SSH_TARGET}" "cd ${REMOTE_DIR} && sudo docker compose ps --format '{{.Name}} {{.State}}' 2>/dev/null" || true)
if echo "${CONTAINERS}" | grep -q "running"; then
    echo "OK"
    PASS=$((PASS + 1))
else
    echo "FAIL"
    FAIL=$((FAIL + 1))
fi

# Check Diode API
echo -n "   Diode API (/diode/docs): "
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${REMOTE_HOST}/diode/docs" 2>/dev/null || echo "000")
if [ "${HTTP_CODE}" = "200" ]; then
    echo "OK (HTTP ${HTTP_CODE})"
    PASS=$((PASS + 1))
else
    echo "FAIL (HTTP ${HTTP_CODE})"
    FAIL=$((FAIL + 1))
fi

# Check OCR service still works
echo -n "   OCR service (/): "
HTTP_CODE_OCR=$(curl -s -o /dev/null -w "%{http_code}" "http://${REMOTE_HOST}/" 2>/dev/null || echo "000")
if [ "${HTTP_CODE_OCR}" != "000" ] && [ "${HTTP_CODE_OCR}" != "502" ] && [ "${HTTP_CODE_OCR}" != "503" ]; then
    echo "OK (HTTP ${HTTP_CODE_OCR})"
    PASS=$((PASS + 1))
else
    echo "WARN (HTTP ${HTTP_CODE_OCR}) - OCR service may not be running"
fi

echo ""
echo "=== Deployment complete ==="
echo "   Passed: ${PASS}, Failed: ${FAIL}"
echo ""
echo "   Diode API:  http://${REMOTE_HOST}/diode/api/"
echo "   Diode Docs: http://${REMOTE_HOST}/diode/docs"
echo "   Diode UI:   http://${REMOTE_HOST}/diode/"

if [ "${FAIL}" -gt 0 ]; then
    echo ""
    echo "WARNING: Some checks failed. Check logs with:"
    echo "   ssh ${SSH_TARGET} 'cd ${REMOTE_DIR} && sudo docker compose logs'"
    exit 1
fi
