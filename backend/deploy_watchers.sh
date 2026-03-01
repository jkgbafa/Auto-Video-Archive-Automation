#!/bin/bash
# Deploy watcher services to VPS
# Run this script on the VPS as root
#
# Usage:
#   sudo bash deploy_watchers.sh
#
# Prerequisites:
#   - Git repo cloned to /root/Auto-Video-Archive-Automation
#   - Python 3 + pip installed
#   - .env file configured in backend/
#   - All token/credential files in place

set -e

REPO_DIR="/root/Auto-Video-Archive-Automation"
BACKEND="$REPO_DIR/backend"

echo "=== Deploying Archive Watcher Services ==="

# Install Python dependencies
echo "[1/5] Installing Python dependencies..."
pip3 install requests python-dotenv gspread 2>/dev/null || pip install requests python-dotenv gspread

# Ensure downloads directory exists
mkdir -p "$BACKEND/downloads"

# Copy service files
echo "[2/5] Installing systemd services..."
cp "$BACKEND/watcher_internxt_icedrive.service" /etc/systemd/system/
cp "$BACKEND/watcher_pcloud_bilibili.service" /etc/systemd/system/

# Reload systemd
echo "[3/5] Reloading systemd..."
systemctl daemon-reload

# Enable services (start on boot)
echo "[4/5] Enabling services..."
systemctl enable watcher_internxt_icedrive.service
systemctl enable watcher_pcloud_bilibili.service

# Start services
echo "[5/5] Starting services..."
systemctl start watcher_internxt_icedrive.service
systemctl start watcher_pcloud_bilibili.service

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Service status:"
systemctl status watcher_internxt_icedrive.service --no-pager -l 2>/dev/null || true
echo ""
systemctl status watcher_pcloud_bilibili.service --no-pager -l 2>/dev/null || true
echo ""
echo "Useful commands:"
echo "  journalctl -u watcher_internxt_icedrive -f    # Follow Internxt->Icedrive logs"
echo "  journalctl -u watcher_pcloud_bilibili -f      # Follow pCloud->Bilibili logs"
echo "  systemctl restart watcher_internxt_icedrive    # Restart service"
echo "  systemctl stop watcher_pcloud_bilibili         # Stop service"
echo "  tail -f /var/log/watcher_internxt_icedrive.log # View log file"
