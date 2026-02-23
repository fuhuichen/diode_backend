#!/bin/bash
set -euo pipefail

LOG="/var/log/diode-setup.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Diode Node Setup Started: $(date) ==="

# --- Configuration (injected by CDK) ---
NODE_TOKEN="{{NODE_TOKEN}}"
BACKEND_URL="{{BACKEND_URL}}"
REGION="{{REGION}}"
NODE_NAME="{{NODE_NAME}}"
DIODE_VERSION="{{DIODE_VERSION}}"

# --- 1. Install system packages ---
echo "Installing system packages..."
dnf install -y unzip python3 python3-pip

# --- 2. Download and install diode binary ---
echo "Installing diode ${DIODE_VERSION}..."
mkdir -p /opt/diode
cd /opt/diode

DOWNLOAD_URL="https://github.com/diodechain/diode_client/releases/download/${DIODE_VERSION}/diode_linux_amd64.zip"
echo "Downloading from ${DOWNLOAD_URL}..."
curl -fsSL -o diode_linux_amd64.zip "$DOWNLOAD_URL"
unzip -o diode_linux_amd64.zip
chmod +x diode
ln -sf /opt/diode/diode /usr/local/bin/diode

echo "Diode installed: $(diode version 2>&1 || echo 'version check skipped')"

# --- 3. Write agent.py ---
echo "Installing diode-agent..."
mkdir -p /opt/diode-agent
cat > /opt/diode-agent/agent.py << 'AGENT_EOF'
{{AGENT_PY_CONTENT}}
AGENT_EOF

# --- 4. Install Python dependencies ---
echo "Installing Python dependencies..."
pip3 install httpx

# --- 5. Write environment file ---
echo "Writing environment config..."
cat > /opt/diode-agent/env << EOF
NODE_TOKEN=${NODE_TOKEN}
BACKEND_URL=${BACKEND_URL}
REGION=${REGION}
NODE_NAME=${NODE_NAME}
EOF

# --- 6. Create diode systemd service ---
echo "Creating diode.service..."
cat > /etc/systemd/system/diode.service << 'SYSTEMD_EOF'
[Unit]
Description=Diode Client SOCKS Proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/diode socksd
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

# --- 7. Create diode-agent systemd service ---
echo "Creating diode-agent.service..."
cat > /etc/systemd/system/diode-agent.service << SYSTEMD_EOF
[Unit]
Description=Diode Node Agent
After=diode.service
Requires=diode.service

[Service]
Type=simple
EnvironmentFile=/opt/diode-agent/env
ExecStartPre=/bin/sleep 15
ExecStart=/usr/bin/python3 /opt/diode-agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

# --- 8. Enable and start services ---
echo "Starting services..."
systemctl daemon-reload
systemctl enable diode.service diode-agent.service
systemctl start diode.service
systemctl start diode-agent.service

echo "=== Diode Node Setup Completed: $(date) ==="
echo "Services status:"
systemctl status diode.service --no-pager || true
systemctl status diode-agent.service --no-pager || true
