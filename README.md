# OverlayCorne

Transparent, always-on-top overlay for the W-Corne (Vial firmware) that shows
the keys you're pressing and the live keymap of whatever layer is currently
held, based on `corne_dvorak_programmer.vil`.

## How it works

The overlay talks to the keyboard over the **Vial/VIA raw HID interface** and
polls the physical switch matrix ~60×/second. That means it sees exactly which
physical switches are down — including the NAV/SYM/FN thumb holds that never
reach Windows — so the displayed layer always matches what the board is doing.

If the board is unplugged or Vial-locked, it automatically falls back to an
**OS keyboard hook**: emitted keycodes are reverse-mapped to physical positions
(approximate — layer holds are invisible to the OS, so the layer is inferred
from the keys you actually type).

Status dot in the header: 🟢 `HID` = matrix mode, 🟠 `OS` = hook fallback,
🔴 `LKD`/`--` = board locked / not found.

## Run

```
pip install -r requirements.txt
python overlay_corne.py          # or double-click OverlayCorne.bat (no console)
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

Position, lock state, and scale persist in `overlay_config.json`.

## CLI options

```
--vil PATH      keymap file (default: corne_dvorak_programmer.vil next to the script)
--scale N       UI scale 0.7–2.0
--margin N      snap margin from screen edge (default 14)
--hz N          matrix poll rate (default 60)
--device STR    substring filter if you have several Vial boards
--no-hid        force OS-hook mode
--reset-pos     ignore saved position, snap bottom-right
--list          list raw-HID keyboards and exit
```

## Display language

- Big legend = tap, small pink legend = hold (home-row mods `Gui/Alt/Ctrl/Shift`, `hold` on the layer thumbs).
- Pink-bordered keys = layer thumbs (NAV / SYM / FN).
- Amber key = currently pressed (pink if it's a layer thumb).
- Dim `▽`-style keys on higher layers = transparent, showing the base key that falls through.
- Layer accents match the field manual: NAV cyan, SYM magenta, FN lime.
- Header: active layer chip, held modifiers, and the last key pressed
  (e.g. `NAV·←`). Combos are recognized too — pressing T+N shows `T+N→(`.

## Notes

- If you re-flash or edit the keymap in Vial, re-export the `.vil` over
  `corne_dvorak_programmer.vil` and restart the overlay.
- Matrix polling requires the board to be **Vial-unlocked** (yours already is).
  If it's ever locked, the overlay shows a banner: press `Ctrl+Alt+U` and hold
  the highlighted keys. Note an unlocked board allows keymap changes/flashing
  by any local app — you can re-lock it from Vial's Security menu when done.
- Running the Vial GUI's matrix tester at the same time is harmless but may
  cause an occasional duplicate poll response.
