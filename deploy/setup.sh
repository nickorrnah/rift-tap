#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh — Full Rift Tap device provisioning
#
# Run this ONCE on a fresh Raspberry Pi 3 A+ (or Zero 2W) after flashing
# Raspberry Pi OS Lite (64-bit, Bookworm).
#
# What this script does:
#   1. Sets the hostname to "rift-tap"
#   2. Configures USB gadget mode (Pi presents as USB Ethernet adapter)
#   3. Assigns a fixed IP to the USB interface and serves DHCP to the laptop
#   4. Installs the Rift Tap app and Python dependencies
#   5. Seeds the card database
#   6. Installs and enables the rift-tap systemd service (auto-starts on boot)
#   7. Enables mDNS so "rift-tap.local" resolves without an IP address
#
# Usage:
#   sudo bash setup.sh
#
# After running:
#   sudo reboot
#
# The device is then ready to ship.  The customer plugs in the USB cable and
# the browser source URL is: http://rift-tap.local:8000/overlay/index.html
# =============================================================================

set -euo pipefail

# ── Colours for output ────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[rift-tap]${NC} $*"; }
warn()  { echo -e "${YELLOW}[rift-tap]${NC} $*"; }
abort() { echo -e "${RED}[rift-tap] ERROR:${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && abort "Run this script as root: sudo bash setup.sh"

APP_DIR="/home/pi/rift-tap"
APP_USER="pi"

# =============================================================================
# 1. Hostname
# =============================================================================
info "Setting hostname to rift-tap..."
hostnamectl set-hostname rift-tap
# Also update /etc/hosts so localhost still resolves correctly
sed -i 's/127\.0\.1\.1.*/127.0.1.1\trift-tap/' /etc/hosts
grep -q "127.0.1.1" /etc/hosts || echo "127.0.1.1	rift-tap" >> /etc/hosts

# =============================================================================
# 2. USB gadget mode
#
# The Pi 3 A+'s micro-USB power port uses the dwc2 controller which supports
# OTG (device/gadget) mode.  We load the g_cdc (CDC Composite) module which
# presents the Pi as a USB Ethernet + serial adapter.
#
# On Pi OS Bookworm the config file is /boot/firmware/config.txt.
# On older Pi OS it is /boot/config.txt.  We detect which is present.
# =============================================================================
info "Configuring USB gadget mode (dwc2)..."

BOOT_CONFIG=""
if [[ -f /boot/firmware/config.txt ]]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
elif [[ -f /boot/config.txt ]]; then
    BOOT_CONFIG="/boot/config.txt"
else
    abort "Cannot find boot config.txt"
fi

CMDLINE=""
if [[ -f /boot/firmware/cmdline.txt ]]; then
    CMDLINE="/boot/firmware/cmdline.txt"
elif [[ -f /boot/cmdline.txt ]]; then
    CMDLINE="/boot/cmdline.txt"
else
    abort "Cannot find cmdline.txt"
fi

# Add dwc2 overlay if not already present
grep -q "dtoverlay=dwc2" "$BOOT_CONFIG" || echo "dtoverlay=dwc2" >> "$BOOT_CONFIG"
info "  dtoverlay=dwc2 → $BOOT_CONFIG"

# Add module loading to cmdline if not already present
if ! grep -q "modules-load=dwc2,g_cdc" "$CMDLINE"; then
    # Append before any trailing newline, on the same line as the rest
    sed -i 's/$/ modules-load=dwc2,g_cdc/' "$CMDLINE"
fi
info "  modules-load=dwc2,g_cdc → $CMDLINE"

# =============================================================================
# 3. USB network interface — fixed IP + DHCP for the laptop
#
# When the Pi boots and the USB cable is plugged in, the kernel creates a
# "usb0" network interface.  We configure it with:
#   - Pi IP:    10.55.55.1  (fixed — this is what the OBS URL points to)
#   - Laptop:   10.55.55.2  (assigned automatically via DHCP)
#
# NetworkManager's "shared" connection type handles all of this in one step:
# static IP on the Pi side + built-in DHCP server for the connected device.
# =============================================================================
info "Configuring usb0 network interface (10.55.55.1)..."

apt-get install -y --no-install-recommends network-manager > /dev/null

# Remove any old connection for usb0 to avoid conflicts
nmcli connection delete rift-tap-usb 2>/dev/null || true

nmcli connection add \
    type ethernet \
    ifname usb0 \
    con-name rift-tap-usb \
    ipv4.method shared \
    ipv4.addresses 10.55.55.1/24 \
    connection.autoconnect yes

info "  Pi USB IP: 10.55.55.1 — laptop will receive 10.55.55.2 via DHCP"

# =============================================================================
# 4. mDNS (rift-tap.local)
#
# avahi-daemon broadcasts the hostname over mDNS so the customer never needs
# to know or type an IP address.
# =============================================================================
info "Enabling mDNS (rift-tap.local)..."
apt-get install -y --no-install-recommends avahi-daemon > /dev/null
systemctl enable avahi-daemon
systemctl start avahi-daemon

# =============================================================================
# 5. I2C (for PN532 NFC HAT)
# =============================================================================
info "Enabling I2C for PN532 HAT..."
raspi-config nonint do_i2c 0   # 0 = enable
apt-get install -y --no-install-recommends i2c-tools python3-smbus > /dev/null

# PN532 HAT DIP switch reminder
warn "Verify PN532 HAT DIP switch: SCL=ON, SDA=ON, all others=OFF"
warn "Verify mode jumpers:          I0=H (right, top pins), I1=L (left, bottom pins)"

# =============================================================================
# 6. App installation
# =============================================================================
info "Installing Rift Tap application..."

# Clone or update the repo
if [[ -d "$APP_DIR/.git" ]]; then
    info "  Updating existing installation..."
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
    info "  Cloning from GitHub..."
    sudo -u "$APP_USER" git clone https://github.com/nickorrnah/rift-tap.git "$APP_DIR"
fi

# Python virtual environment
# --system-site-packages lets the venv use system lgpio/RPi.GPIO
# which avoids needing to compile C extensions from source.
info "  Setting up Python venv..."
apt-get install -y --no-install-recommends \
    python3-venv python3-pip python3-lgpio python3-rpi.gpio swig > /dev/null
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv" --system-site-packages

# Install core dependencies from PyPI directly.
# piwheels sometimes ships broken wheels for newer Python versions;
# forcing PyPI ensures we get the correct packages.
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet \
    --index-url https://pypi.org/simple \
    -r "$APP_DIR/requirements.txt"

# Install Adafruit NFC libraries
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet \
    adafruit-circuitpython-pn532 adafruit-blinka RPi.GPIO smbus2 || \
    warn "  NFC libraries not fully installed — may need manual fix"

# =============================================================================
# 7. Environment configuration
# =============================================================================
info "Writing .env configuration..."
ENV_FILE="$APP_DIR/.env"
cat > "$ENV_FILE" <<EOF
# Rift Tap device configuration
# Generated by setup.sh — edit as needed

SIMULATE_NFC=false
NFC_INTERFACE=I2C
HOST=0.0.0.0
PORT=8000
DISPLAY_DURATION=8
EOF
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"   # restrict read to owner only

# =============================================================================
# 8. Seed the database
# =============================================================================
info "Seeding card database..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/seed_db.py"

# =============================================================================
# 9. Systemd service
# =============================================================================
info "Installing rift-tap systemd service..."
cp "$APP_DIR/deploy/rift-tap.service" /etc/systemd/system/rift-tap.service
systemctl daemon-reload
systemctl enable rift-tap
info "  Service enabled — will auto-start on every boot"

# =============================================================================
# 10. LED control permissions
#
# The app blinks the ACT LED on card scans.  The sysfs LED interface requires
# write permission.  We add the pi user to the gpio group and set udev rules.
# =============================================================================
info "Configuring LED permissions..."
usermod -aG gpio "$APP_USER" 2>/dev/null || true
cat > /etc/udev/rules.d/99-rift-tap-led.rules <<'EOF'
# Allow the rift-tap service user to control the ACT LED without sudo
SUBSYSTEM=="leds", ACTION=="add", RUN+="/bin/chmod g+w /sys/class/leds/%k/brightness /sys/class/leds/%k/trigger"
EOF

# =============================================================================
# 11. Quality-of-life tweaks
# =============================================================================
info "Applying system tweaks..."

# Disable WiFi power management — the default power-save mode causes the
# radio to sleep after inactivity, adding 500ms–2s of latency on the next
# request which makes the server feel unresponsive.
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/wifi-powersave-off.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF

# Disable USB autosuspend — the dwc2 gadget link the laptop connects
# through can otherwise get suspended by the kernel after a period of
# inactivity, which drops the usb0 connection until the next burst of
# traffic wakes it back up. We want it always on while the device is
# powered, so disable autosuspend globally via the kernel cmdline...
grep -q "usbcore.autosuspend=-1" "$CMDLINE" || sed -i 's/$/ usbcore.autosuspend=-1/' "$CMDLINE"
info "  usbcore.autosuspend=-1 → $CMDLINE"

# ...and reinforce it with a udev rule, since autosuspend can otherwise be
# re-enabled per-device by the kernel/driver on hotplug (e.g. unplugging
# and replugging the USB cable) independently of the boot-time cmdline value.
cat > /etc/udev/rules.d/99-rift-tap-usb-power.rules <<'EOF'
# Keep every USB device (including the dwc2 gadget link to the laptop)
# powered on at all times — never let the kernel autosuspend it.
SUBSYSTEM=="usb", ATTR{power/control}="on"
EOF

# Faster boot: disable waiting for network during boot (we manage networking)
systemctl disable NetworkManager-wait-online.service 2>/dev/null || true

# Disable swap to reduce SD card wear (512MB RAM is enough for this app)
systemctl disable dphys-swapfile 2>/dev/null || true
dphys-swapfile swapoff 2>/dev/null || true

# Reduce GPU memory split (no display needed on Standard model)
grep -q "gpu_mem=16" "$BOOT_CONFIG" || echo "gpu_mem=16" >> "$BOOT_CONFIG"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Rift Tap setup complete!                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
info "Next step:  sudo reboot"
echo ""
info "After reboot, plug in the USB cable and open:"
info "  http://rift-tap.local:8000/overlay/index.html  (OBS browser source)"
info "  http://rift-tap.local:8000/admin               (card assignment)"
echo ""
warn "I2C check (after reboot, run this to confirm NFC HAT is detected):"
warn "  i2cdetect -y 1   →  should show address 0x24"
echo ""
