# OverlayCorne

Transparent, always-on-top overlay for the Pilot W-Corne (Vial firmware) that
shows the keys you're pressing and the live keymap of whatever layer is
currently held, based on `corne_dvorak_programmer.vil`.

Runs on **Windows** and **Linux** (X11/XWayland; developed against Fedora +
GNOME Wayland).

## How it works

The overlay talks to the keyboard over the **Vial/VIA raw HID interface** and
polls the physical switch matrix ~60×/second. That means it sees exactly which
physical switches are down — including the NAV/SYM/FN thumb holds that never
reach the OS — so the displayed layer always matches what the board is doing.

If the board is unplugged or Vial-locked, it automatically falls back to an
**OS keyboard hook** (Windows: low-level hook; Linux: evdev): emitted keycodes
are reverse-mapped to physical positions. This mode is approximate by nature —
layer holds are invisible to the OS, the layer is inferred from the keys you
actually type, and when the same keycode lives on two physical keys (both
Backspaces, say) the overlay can only guess which one you pressed. **If layer
holds don't show and presses light the wrong twin key, you are in hook mode —
fix the HID permissions below.**

Status dot in the header: 🟢 `HID` = matrix mode, 🟠 `OS` = hook fallback,
🔴 `LKD`/`--` = board locked / not found.

## Install & run: Linux (Fedora / Debian / Ubuntu / Arch)

One-time setup — installs the dependencies and the udev rules, then reloads
udev:

```bash
sudo scripts/install.sh              # add --autostart for launch-on-plug
# unplug/replug the keyboard, then run AS YOUR NORMAL USER:
python3 overlay_corne.py
```

Do **not** launch the overlay itself with `sudo`: root's Python won't see your
pip-installed `hidapi`, so the overlay silently degrades to hook mode — and
the GUI, config and pidfile all end up owned by root. The udev rule makes
sudo unnecessary.

<details>
<summary>Manual steps (what install.sh does, Fedora naming)</summary>

```bash
sudo dnf install python3 python3-tkinter python3-evdev python3-pip
pip install --user hidapi            # if python3-hidapi isn't packaged

# HID + evdev access for the board (one-time; do NOT run the overlay as root)
sudo install -m0644 udev/70-vial.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
# now unplug/replug the keyboard, then verify:
getfacl /dev/hidraw* 2>/dev/null | grep -B3 "user:$USER"   # expect rw on the W-CORNE nodes
```

On Debian/Ubuntu the packages are `python3-tk python3-evdev python3-hidapi`;
on Arch `tk python-evdev python-hidapi`.
</details>

`udev/70-vial.rules` grants your logged-in session access to the Vial hidraw
interface and to the W-CORNE's evdev nodes only (deliberately not the broad
`input` group, which would let every app read every input device — i.e.
keylogging-wide access). The `70-` prefix is load-bearing: `TAG+="uaccess"`
is processed by systemd's `73-seat-late.rules`, so a `99-*.rules` copy of the
same rules would be silently ignored.

## Install & run: Windows

```bat
pip install -r requirements.txt
python overlay_corne.py          :: or double-click OverlayCorne.bat (no console)
```

First launch snaps to the bottom-right of the work area.

## Controls

| Input | Action |
|---|---|
| `Ctrl+Alt+K` | Lock / unlock position. **Locked = fully click-through.** |
| `Ctrl+Alt+Shift+K` | Quit |
| `Ctrl+Alt+U` | Start the Vial unlock handshake (only if the board reports locked) |
| Left-drag (unlocked) | Move the overlay |
| Right-click (unlocked) | Menu: lock, snap bottom-right, scale ±, quit |

Position, lock state, and scale persist in `%APPDATA%\OverlayCorne\` (Windows)
or `~/.config/OverlayCorne/` (Linux).

### Linux hotkey notes

Wayland does not let apps grab global hotkeys, so on Linux the hotkeys are
detected via evdev (needs the udev rule above) and — unlike Windows — the
keystroke still reaches the focused app. Three ways to control the overlay,
in order of preference:

1. The `Ctrl+Alt+K` / `Ctrl+Alt+U` / `Ctrl+Alt+Shift+K` combos (evdev).
2. Control verbs from any terminal or a GNOME custom shortcut
   (Settings → Keyboard → View and Customize Shortcuts → Custom):
   ```bash
   python3 overlay_corne.py --toggle-lock   # lock/unlock position
   python3 overlay_corne.py --kb-unlock     # Vial unlock handshake
   python3 overlay_corne.py --stop          # quit
   ```
3. Last-resort rescue for a locked (click-through) overlay:
   `pkill -USR1 -f overlay_corne`

## CLI options

```
--vil PATH      keymap file (default: corne_dvorak_programmer.vil next to the script/exe)
--scale N       UI scale 0.7–2.0
--margin N      snap margin from screen edge (default 14)
--hz N          matrix poll rate (default 60)
--device STR    substring filter if you have several Vial boards
--no-hid        force OS-hook mode
--reset-pos     ignore saved position, snap bottom-right
--list          list raw-HID keyboards and exit
--toggle-lock / --kb-unlock / --stop    control a running instance (Linux)
```

## Display language

- Big legend = tap, small pink legend = hold (home-row mods `Gui/Alt/Ctrl/Shift`, `hold` on the layer thumbs).
- Pink-bordered keys = layer thumbs (NAV / SYM / FN).
- Amber key = currently pressed (pink if it's a layer thumb).
- Dim `▽`-style keys on higher layers = transparent, showing the base key that falls through.
- Layer accents: NAV cyan, SYM magenta, FN lime.
- Header: active layer chip, held modifiers, and the last key pressed
  (e.g. `NAV·←`). Combos are recognized too — pressing T+N shows `T+N→(`.
- The rendered shape matches the physical W-Corne: two column-staggered 3×6
  halves, two inner-edge keys per half, three thumbs per half. If your build
  differs, tweak `build_physical_layout()` / `COL_STAGGER` in
  `overlay_corne.py`.

## Building a distributable executable

PyInstaller cannot cross-compile — build the Windows binary on Windows and the
Linux binary on Linux (or let CI do both, see below).

**Windows** (produces `dist\OverlayCorne.exe`):

```bat
py -m pip install pyinstaller hidapi
py -m PyInstaller --onefile --noconsole --name OverlayCorne ^
  --add-data "corne_dvorak_programmer.vil;." overlay_corne.py
```

**Linux** (produces `dist/overlaycorne`):

```bash
python3 -m pip install --user pyinstaller
python3 -m PyInstaller --onefile --name overlaycorne \
  --add-data "corne_dvorak_programmer.vil:." \
  --hidden-import evdev overlay_corne.py
install -Dm755 dist/overlaycorne ~/.local/bin/overlaycorne
```

Notes:

- Python 3.14 needs PyInstaller ≥ 6.16; CI pins Python 3.12 to be safe.
- A `.vil` placed **next to the executable** overrides the bundled one — no
  rebuild needed after re-exporting your keymap from Vial (restart required).
- Linux binaries require the target machine's glibc to be at least as new as
  the build machine's; the CI builds on ubuntu-22.04 for wide compatibility.
  A binary built on Fedora is fine for that same Fedora box.
- Windows antivirus occasionally flags PyInstaller onefile binaries; building
  with `--onedir` instead (or code-signing) avoids that.

### Automated builds (GitHub Actions)

`.github/workflows/release.yml` builds both binaries on every push of a `v*`
tag and attaches them to a GitHub Release for download:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

## Autostart & launch-on-plug

**Fedora — start when the keyboard is plugged in** (recommended):

```bash
install -Dm644 systemd/overlaycorne.service ~/.config/systemd/user/overlaycorne.service
systemctl --user daemon-reload
```

The last rule in `udev/70-vial.rules` then starts the service whenever the
board appears. Requirements: you're logged in, and the user manager knows your
display (check `systemctl --user show-environment | grep -E 'DISPLAY|WAYLAND'`;
on GNOME it does). Status: `systemctl --user status overlaycorne`.

For plain start-at-login instead: `systemctl --user enable overlaycorne`, or
copy `OverlayCorne.desktop` to `~/.config/autostart/`.

**Windows — start when the keyboard is plugged in:**

```bat
schtasks /Create /TN "OverlayCorne on plug" /XML tools\OverlayCorne-onplug.xml
```

Edit the `<Command>` path in the XML first. The task also runs at logon, and
"IgnoreNew" keeps it single-instance.

### Can it auto-install itself from the keyboard/dongle?

No. The keyboard is a HID device, not a storage drive, and modern operating
systems removed USB autorun entirely (it was a malware vector) — no device can
silently install software on an unprepared machine. The launch-on-plug setups
above are the legitimate equivalent: a **one-time setup per machine**, after
which plugging the board in brings the overlay up automatically. (The only
zero-setup technique — a device that injects keystrokes to install software,
"BadUSB" — is indistinguishable from an attack and deliberately not part of
this project.)

## Troubleshooting

- **Keys light up but layer holds do nothing / wrong twin key lights** — you
  are in hook mode (🟠 `OS` dot). Install the udev rule, replug the board, and
  don't use `sudo`.
- **Red dot, `--`, board plugged in** — hidraw permissions missing (udev rule
  not installed / not triggered) or another `--device` filter mismatch. Check
  `python3 overlay_corne.py --list`.
- **"evdev: no readable keyboards"** — the evdev udev line didn't apply
  (replug the board) — hook fallback and evdev hotkeys stay off, HID mode and
  the control verbs still work.
- **Overlay looks blurry on Linux** — XWayland fractional scaling; use
  `--scale` instead of desktop zoom.
- **Locked overlay you can't reach** — `python3 overlay_corne.py
  --toggle-lock` or `pkill -USR1 -f overlay_corne`.
- If you re-flash or edit the keymap in Vial, re-export the `.vil` over
  `corne_dvorak_programmer.vil` (or drop it next to the packaged executable)
  and restart the overlay.
- Matrix polling requires the board to be **Vial-unlocked**. If it's locked,
  the overlay shows a banner: press `Ctrl+Alt+U` (or `--kb-unlock`) and hold
  the highlighted keys. An unlocked board allows keymap changes by any local
  app — you can re-lock it from Vial's Security menu when done.
