#!/usr/bin/env bash
# Pi-hole Docker setup for Ubuntu 24.04 (Latitude 192.168.1.210)
# Run as: sudo bash setup.sh
#
# What this does:
#   1. Installs Docker Engine + Compose plugin (if not already installed)
#   2. Fixes systemd-resolved port 53 conflict
#   3. Starts Pi-hole container
#   4. Verifies DNS resolution
#
# After running this script:
#   - Pi-hole admin UI: http://192.168.1.210:8080/admin
#   - Set your router's DHCP DNS to 192.168.1.210 for network-wide blocking
#   - Or configure DNS per-device if your router doesn't support custom DNS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Pi-hole Setup for Home Hub ==="

# --- Step 1: Docker ---
if command -v docker &>/dev/null; then
    echo "[OK] Docker is already installed: $(docker --version)"
else
    echo "[*] Installing Docker Engine..."
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
      https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    echo "[OK] Docker installed"
fi

# Add current user to docker group (if not root)
if [ "$EUID" -ne 0 ] || [ -n "${SUDO_USER:-}" ]; then
    REAL_USER="${SUDO_USER:-$(whoami)}"
    if ! groups "$REAL_USER" | grep -q docker; then
        usermod -aG docker "$REAL_USER"
        echo "[OK] Added $REAL_USER to docker group (re-login to take effect)"
    fi
fi

# --- Step 2: Fix systemd-resolved port 53 conflict ---
if ss -lntu | grep -q '127.0.0.53:53'; then
    echo "[*] Disabling systemd-resolved DNS stub (freeing port 53)..."

    # Create static resolv.conf BEFORE disabling the stub
    # so the machine doesn't lose DNS during the transition
    rm -f /etc/resolv.conf
    cat > /etc/resolv.conf <<EOF
# Static resolv.conf for Pi-hole setup
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF

    # Disable the stub listener
    mkdir -p /etc/systemd/resolved.conf.d
    cat > /etc/systemd/resolved.conf.d/no-stub.conf <<EOF
[Resolve]
DNSStubListener=no
EOF

    systemctl restart systemd-resolved
    echo "[OK] systemd-resolved stub disabled, port 53 free"
else
    echo "[OK] Port 53 is already free"
fi

# --- Step 3: Set Pi-hole password ---
if [ -z "${PIHOLE_PASSWORD:-}" ]; then
    read -rsp "Set Pi-hole admin password: " PIHOLE_PASSWORD
    echo
    export PIHOLE_PASSWORD
fi

# --- Step 4: Start Pi-hole ---
echo "[*] Starting Pi-hole container..."
docker compose up -d

echo "[*] Waiting for Pi-hole to initialize (15s)..."
sleep 15

# --- Step 5: Verify ---
echo "[*] Verifying DNS resolution..."
if command -v dig &>/dev/null; then
    if dig @127.0.0.1 google.com +short | grep -q .; then
        echo "[OK] DNS resolution working via Pi-hole"
    else
        echo "[WARN] DNS resolution test failed — Pi-hole may still be starting"
    fi
else
    echo "[SKIP] dig not installed, install with: apt-get install dnsutils"
fi

echo ""
echo "=== Pi-hole is running ==="
echo "Admin UI:  http://192.168.1.210:8080/admin"
echo "DNS:       192.168.1.210:53"
echo ""
echo "Next steps:"
echo "  1. Open the admin UI and verify it's working"
echo "  2. Set your router's DHCP DNS server to 192.168.1.210"
echo "     (or configure DNS per-device if your router doesn't support it)"
echo "  3. Add these to your Home Hub .env on the Latitude:"
echo "     PIHOLE_API_URL=http://localhost:8080"
echo "     PIHOLE_API_KEY=$PIHOLE_PASSWORD"
echo "  4. Restart home-hub.service: sudo systemctl restart home-hub"
