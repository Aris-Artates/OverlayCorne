#!/usr/bin/env bash
# OverlayCorne Linux installer: dependencies + udev rules (+ optional autostart).
#
#   sudo scripts/install.sh [--autostart]
#
# Run it with sudo FROM YOUR OWN SESSION (it uses $SUDO_USER to set up pip and
# systemd for you).  Do NOT run the overlay itself as root afterwards — the
# whole point of the udev rule is that root isn't needed.
#
# Supported: Fedora (dnf), Debian/Ubuntu (apt), Arch (pacman).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AUTOSTART=0
[[ "${1:-}" == "--autostart" ]] && AUTOSTART=1

if [[ $EUID -ne 0 ]]; then
    echo "This installer needs root for packages and udev rules." >&2
    echo "Re-run as:  sudo $0 ${1:-}" >&2
    exit 1
fi
if [[ -z "${SUDO_USER:-}" || "$SUDO_USER" == "root" ]]; then
    echo "Run via sudo from your normal user session (not a root login)," >&2
    echo "so the per-user steps (pip, systemd --user) target your account." >&2
    exit 1
fi

USER_UID="$(id -u "$SUDO_USER")"
USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"

as_user() {
    sudo -u "$SUDO_USER" -H "$@"
}

step() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- packages --
step "Installing system packages"
if command -v dnf >/dev/null; then
    dnf install -y python3 python3-tkinter python3-evdev python3-pip
    HIDAPI_DISTRO_PKG="python3-hidapi"
    PKG_INSTALL=(dnf install -y)
elif command -v apt-get >/dev/null; then
    apt-get update
    apt-get install -y python3 python3-tk python3-evdev python3-pip
    HIDAPI_DISTRO_PKG="python3-hidapi"
    PKG_INSTALL=(apt-get install -y)
elif command -v pacman >/dev/null; then
    pacman -S --needed --noconfirm python tk python-evdev python-pip
    HIDAPI_DISTRO_PKG="python-hidapi"
    PKG_INSTALL=(pacman -S --needed --noconfirm)
else
    echo "No supported package manager found (dnf/apt/pacman)." >&2
    echo "Install python3 + tkinter + evdev + hidapi yourself, then re-run" >&2
    echo "this script to set up the udev rules." >&2
    exit 1
fi

# ----------------------------------------------------------------- hidapi ---
# The overlay imports `hid` (cython-hidapi).  Prefer the distro package;
# fall back to a per-user pip install (--break-system-packages covers
# PEP 668 "externally managed" distros — it only touches ~/.local).
step "Installing python hidapi bindings"
if ! "${PKG_INSTALL[@]}" "$HIDAPI_DISTRO_PKG" 2>/dev/null; then
    echo "distro package $HIDAPI_DISTRO_PKG unavailable -> pip --user fallback"
    as_user python3 -m pip install --user hidapi 2>/dev/null ||
        as_user python3 -m pip install --user --break-system-packages hidapi
fi
if ! as_user python3 -c "import hid" 2>/dev/null; then
    echo "WARNING: 'import hid' still fails for $SUDO_USER — the overlay" >&2
    echo "will run in OS-hook fallback mode until hidapi is importable." >&2
fi

# ------------------------------------------------------------------- udev ---
# 70-vial.rules grants your logged-in session access to the Vial hidraw
# interface + the W-CORNE evdev nodes via TAG+="uaccess".  The filename must
# sort before systemd's 73-seat-late.rules or uaccess is silently ignored —
# that's why it is NOT named 99-*.rules.
step "Installing udev rules (udev/70-vial.rules)"
install -m0644 "$REPO/udev/70-vial.rules" /etc/udev/rules.d/70-vial.rules
udevadm control --reload-rules
udevadm trigger

# -------------------------------------------------------------- autostart ---
if [[ $AUTOSTART -eq 1 ]]; then
    step "Installing systemd user service (launch on keyboard plug)"
    as_user install -Dm644 "$REPO/systemd/overlaycorne.service" \
        "$USER_HOME/.config/systemd/user/overlaycorne.service"
    if ! as_user env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
            systemctl --user daemon-reload; then
        echo "daemon-reload failed (no user session bus?) — run manually:" >&2
        echo "  systemctl --user daemon-reload" >&2
    fi
    echo "NOTE: edit ExecStart in ~/.config/systemd/user/overlaycorne.service"
    echo "if you run from source instead of ~/.local/bin/overlaycorne."
fi

# ------------------------------------------------------------------ done ----
step "Done — finish up:"
cat <<EOF
  1. Unplug and replug the keyboard (applies the new udev rules).
  2. Verify access (expect rw for $SUDO_USER on the W-CORNE nodes):
       getfacl /dev/hidraw* 2>/dev/null | grep -B3 "user:$SUDO_USER"
  3. Run the overlay AS YOUR NORMAL USER (never sudo):
       python3 $REPO/overlay_corne.py
     Green 'HID' dot = matrix mode; orange 'OS' dot = permissions still wrong.
EOF
