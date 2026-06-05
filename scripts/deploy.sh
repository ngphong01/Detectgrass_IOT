#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Weed Detection System — Auto Deploy Script cho Raspberry Pi
# Usage: sudo bash scripts/deploy.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
step() { echo -e "\n${YELLOW}[$1/10]${NC} $2"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PI_USER="${SUDO_USER:-pi}"

echo "============================================"
echo "  Weed Detection System — Auto Deploy"
echo "  Project: $PROJECT_DIR"
echo "  User: $PI_USER"
echo "============================================"

step 1 "Updating OS packages..."
apt update -qq && apt upgrade -y -qq && ok "OS updated"

step 2 "Installing system packages..."
apt install -y -qq python3-pip python3-opencv i2c-tools python3-picamera2
ok "System packages installed"

step 3 "Installing pip packages..."
pip3 install --break-system-packages ultralytics opencv-python numpy flask paho-mqtt 2>/dev/null || \
pip3 install ultralytics opencv-python numpy flask paho-mqtt
pip3 install --break-system-packages adafruit-circuitpython-servokit 2>/dev/null || \
pip3 install adafruit-circuitpython-servokit
pip3 install --break-system-packages RPi.GPIO 2>/dev/null || true
ok "pip packages installed"

step 4 "Enabling I2C interface..."
raspi-config nonint do_i2c 0
ok "I2C enabled"

step 5 "Enabling Camera interface..."
raspi-config nonint do_camera 0
ok "Camera enabled"

step 6 "Adding user '$PI_USER' to hardware groups..."
usermod -aG gpio,i2c,video,dialout "$PI_USER" 2>/dev/null || true
ok "User groups updated"

step 7 "Creating folders..."
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/captures" "$PROJECT_DIR/models"
ok "Folders created"

step 8 "Setting permissions..."
chmod 755 "$PROJECT_DIR/logs" "$PROJECT_DIR/captures" "$PROJECT_DIR/models"
chmod +x "$PROJECT_DIR/scripts/"*.sh 2>/dev/null || true
chmod +x "$PROJECT_DIR/scripts/"*.py 2>/dev/null || true
ok "Permissions set"

step 9 "Verifying I2C (PCA9685 at 0x40)..."
if i2cdetect -y 1 2>/dev/null | grep -q "40"; then
    ok "PCA9685 detected at 0x40"
else
    warn "PCA9685 not detected — check wiring"
fi

step 10 "Installing systemd service..."
SERVICE_FILE="$PROJECT_DIR/scripts/weed-detect.service"
if [ -f "$SERVICE_FILE" ]; then
    cp "$SERVICE_FILE" /etc/systemd/system/weed-detect.service
    sed -i "s|/home/pi/detect-iot|$PROJECT_DIR|g" /etc/systemd/system/weed-detect.service
    systemctl daemon-reload
    ok "Service installed. Enable: sudo systemctl enable weed-detect"
else
    warn "Service file not found, skipping"
fi

echo ""
echo "============================================"
echo -e "${GREEN} Deploy complete!${NC}"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Copy model:  scp best.pt ${PI_USER}@<ip>:$PROJECT_DIR/models/"
echo "  2. Reboot:      sudo reboot"
echo "  3. Auto-start:  sudo systemctl enable --now weed-detect"
echo "  4. Watch log:   sudo journalctl -u weed-detect -f"
echo "  5. Dashboard:   http://<pi-ip>:5000"
echo ""
