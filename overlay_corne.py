#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OverlayCorne — transparent, always-on-top keyboard overlay for a Vial Corne.

Renders the keymap from a Vial .vil export and lights up the physical keys you
are pressing, switching the displayed legends to whatever layer is currently
held on the board.

Input sources
  HID mode (primary)   : polls the keyboard's switch matrix over Vial/VIA raw
                         HID.  Exact physical key state + true layer holds.
  OS hook mode (backup): a low-level keyboard hook maps the keycodes Windows
                         receives back to physical positions (approximate).
                         Used automatically when the board is unreachable or
                         Vial-locked.

Hotkeys (global)
  Ctrl+Alt+K         lock / unlock the overlay position (locked = click-through)
  Ctrl+Alt+U         start the Vial unlock handshake (only if the board is locked)
  Ctrl+Alt+Shift+K   quit the overlay

Mouse (only while unlocked)
  Left-drag          move the overlay
  Right-click        context menu (lock, snap bottom-right, scale, quit)
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import NamedTuple, Optional

try:
    import hid
except ImportError:
    hid = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VIL = os.path.join(APP_DIR, "corne_dvorak_programmer.vil")
CONFIG_PATH = os.path.join(APP_DIR, "overlay_config.json")

RAW_USAGE_PAGE = 0xFF60
RAW_USAGE = 0x61
MSG_LEN = 32

# ---------------------------------------------------------------- colors ----
TRANSPARENT = "#010203"        # color-keyed away -> fully see-through
PANEL = "#0f1620"
KEY_BG = "#16202e"
KEY_BG_LAYER = "#1c1420"
EDGE = "#22303f"
INK = "#c8d6e5"
DIM = "#5a6b7d"
AMBER = "#ffb347"
CYAN = "#4fd6e0"
MAGENTA = "#e05a8a"
LIME = "#9fe870"
DARK = "#0a0e14"
RED = "#ff5566"

LAYER_NAMES = {0: "BASE", 1: "NAV", 2: "SYM", 3: "FN"}
LAYER_ACCENT = {0: INK, 1: CYAN, 2: MAGENTA, 3: LIME}

# ------------------------------------------------------------- keycodes -----
SIMPLE = {
    "KC_TAB": "Tab", "KC_ESC": "Esc", "KC_ESCAPE": "Esc",
    "KC_ENT": "Ent", "KC_ENTER": "Ent",
    "KC_SPC": "Spc", "KC_SPACE": "Spc",
    "KC_BSPC": "Bksp", "KC_BSPACE": "Bksp",
    "KC_DEL": "Del", "KC_DELETE": "Del", "KC_INS": "Ins", "KC_CAPS": "Caps",
    "KC_LSFT": "Shift", "KC_RSFT": "Shift",
    "KC_LCTL": "Ctrl", "KC_RCTL": "Ctrl",
    "KC_LALT": "Alt", "KC_RALT": "AltGr",
    "KC_LGUI": "Win", "KC_RGUI": "Win", "KC_APP": "Menu",
    "KC_QUOTE": "'", "KC_QUOT": "'", "KC_DQUO": '"',
    "KC_COMMA": ",", "KC_COMM": ",", "KC_DOT": ".",
    "KC_SLASH": "/", "KC_SLSH": "/",
    "KC_SCOLON": ";", "KC_SCLN": ";",
    "KC_MINS": "-", "KC_MINUS": "-", "KC_EQL": "=", "KC_EQUAL": "=",
    "KC_LBRC": "[", "KC_RBRC": "]", "KC_BSLS": "\\",
    "KC_GRV": "`", "KC_GRAVE": "`",
    "KC_TILD": "~", "KC_EXLM": "!", "KC_AT": "@", "KC_HASH": "#",
    "KC_DLR": "$", "KC_PERC": "%", "KC_CIRC": "^", "KC_AMPR": "&",
    "KC_ASTR": "*", "KC_LPRN": "(", "KC_RPRN": ")",
    "KC_UNDS": "_", "KC_PLUS": "+", "KC_LCBR": "{", "KC_RCBR": "}",
    "KC_PIPE": "|", "KC_COLN": ":", "KC_QUES": "?", "KC_LT": "<", "KC_GT": ">",
    "KC_LEFT": "←", "KC_DOWN": "↓", "KC_UP": "↑",
    "KC_RGHT": "→", "KC_RIGHT": "→",
    "KC_HOME": "Home", "KC_END": "End", "KC_PGUP": "PgUp", "KC_PGDN": "PgDn",
    "KC_PSCR": "PrtSc",
    "KC_MS_U": "M↑", "KC_MS_D": "M↓",
    "KC_MS_L": "M←", "KC_MS_R": "M→",
    "KC_WH_U": "W↑", "KC_WH_D": "W↓",
    "KC_WH_L": "W←", "KC_WH_R": "W→",
    "KC_BTN1": "LClk", "KC_BTN2": "RClk", "KC_BTN3": "MClk",
    "KC_BTN4": "B4", "KC_BTN5": "B5",
    "KC_MUTE": "Mute", "KC_VOLU": "Vol+", "KC_VOLD": "Vol-",
    "KC_MPRV": "Prev", "KC_MPLY": "Play", "KC_MNXT": "Next",
    "KC_PSLS": "/", "KC_PAST": "*", "KC_PPLS": "+", "KC_PMNS": "-",
    "KC_PDOT": ".", "KC_PEQL": "=", "KC_PENT": "Ent",
    "QK_BOOT": "Boot", "RESET": "Boot",
    "QK_CAPS_WORD_TOGGLE": "CapsW", "CAPS_WORD": "CapsW",
    "KC_NO": "", "KC_TRNS": "▽", "KC_TRANSPARENT": "▽",
}
RE_LETTER = re.compile(r"^KC_([A-Z])$")
RE_DIGIT = re.compile(r"^KC_(\d)$")
RE_FKEY = re.compile(r"^KC_F(\d{1,2})$")
RE_PNUM = re.compile(r"^KC_P(\d)$")
RE_LT = re.compile(r"^LT\((\d+),\s*(\w+)\)$")
RE_MT = re.compile(r"^MT\(([A-Z_|]+),\s*(\w+)\)$")
RE_WRAP = re.compile(r"^([A-Z]{1,3})\((\w+)\)$")

MOD_LABEL = {
    "MOD_LSFT": "Shift", "MOD_RSFT": "Shift",
    "MOD_LCTL": "Ctrl", "MOD_RCTL": "Ctrl",
    "MOD_LALT": "Alt", "MOD_RALT": "Alt",
    "MOD_LGUI": "Gui", "MOD_RGUI": "Gui",
}
NICE_SHORTCUT = {
    ("C", "KC_Z"): "Undo", ("C", "KC_Y"): "Redo", ("C", "KC_X"): "Cut",
    ("C", "KC_C"): "Copy", ("C", "KC_V"): "Paste",
}
WRAP_PREFIX = {"C": "^", "S": "⇧", "A": "⎇", "G": "⊞"}


def base_label(name: str) -> str:
    if name in SIMPLE:
        return SIMPLE[name]
    for rx, fmt in ((RE_LETTER, "{0}"), (RE_DIGIT, "{0}"),
                    (RE_FKEY, "F{0}"), (RE_PNUM, "{0}")):
        m = rx.match(name)
        if m:
            return fmt.format(m.group(1))
    return name[3:] if name.startswith("KC_") else name


class Key(NamedTuple):
    tap: str                 # big legend
    hold: str                # small legend under it ('' = none)
    kind: str                # plain | mod | layer | shortcut | trns | none
    tapname: str             # underlying KC_* emitted on tap ('' if none)
    layer: int               # LT target layer (-1 if not a layer key)
    fn: str                  # wrapper fn for shortcut kind ('' otherwise)


_key_cache: dict = {}


def parse_key(kc) -> Optional[Key]:
    if kc is None or kc == -1:
        return None
    if kc in _key_cache:
        return _key_cache[kc]

    key = None
    m = RE_LT.match(kc)
    if m:
        layer, inner = int(m.group(1)), m.group(2)
        tap = LAYER_NAMES.get(layer, f"L{layer}") if inner == "KC_NO" \
            else base_label(inner)
        key = Key(tap, "hold", "layer", "" if inner == "KC_NO" else inner,
                  layer, "")
    if key is None:
        m = RE_MT.match(kc)
        if m:
            mods, inner = m.group(1), m.group(2)
            hold = "+".join(dict.fromkeys(
                MOD_LABEL.get(p, p) for p in mods.split("|")))
            key = Key(base_label(inner), hold, "mod", inner, -1, "")
    if key is None:
        m = RE_WRAP.match(kc)
        if m and not kc.startswith("KC_"):
            fn, inner = m.group(1), m.group(2)
            tap = NICE_SHORTCUT.get(
                (fn, inner), WRAP_PREFIX.get(fn, fn) + base_label(inner))
            key = Key(tap, "", "shortcut", inner, -1, fn)
    if key is None:
        kind = "trns" if kc in ("KC_TRNS", "KC_TRANSPARENT") else \
               "none" if kc == "KC_NO" else "plain"
        key = Key(base_label(kc), "", kind, kc, -1, "")

    _key_cache[kc] = key
    return key


# --------------------------------------------------------------- keymap -----
class Keymap:
    def __init__(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.layers = data["layout"]
        self.rows = len(self.layers[0])
        self.cols = len(self.layers[0][0])
        self.positions = [(r, c)
                          for r in range(self.rows)
                          for c in range(self.cols)
                          if self.layers[0][r][c] != -1]
        # LT keys on the base layer -> which layer they momentarily enable
        self.lt_pos = {}
        for (r, c) in self.positions:
            k = parse_key(self.layers[0][r][c])
            if k and k.kind == "layer":
                self.lt_pos[(r, c)] = k.layer
        # combos: (frozenset of trigger KC names, result KC name)
        self.combos = []
        for entry in data.get("combo", []):
            trig = frozenset(k for k in entry[:4] if k != "KC_NO")
            if trig and entry[4] != "KC_NO":
                self.combos.append((trig, entry[4]))

    def resolve(self, layer: int, r: int, c: int):
        """Keycode at (r,c) on `layer`, falling through KC_TRNS to base."""
        kc = self.layers[layer][r][c]
        if kc == -1:
            return None
        if kc in ("KC_TRNS", "KC_TRANSPARENT") and layer != 0:
            return self.layers[0][r][c]
        return kc

    def is_trns(self, layer: int, r: int, c: int) -> bool:
        return self.layers[layer][r][c] in ("KC_TRNS", "KC_TRANSPARENT")

    def tapname_at_base(self, r: int, c: int) -> str:
        k = parse_key(self.layers[0][r][c])
        return k.tapname if k else ""


def build_outmaps(km: Keymap):
    """Per layer: emitted-keycode-name -> position, for the OS-hook fallback."""
    outmap = [{} for _ in range(4)]
    ctrlmap = [{} for _ in range(4)]
    for L in range(4):
        for (r, c) in km.positions:
            k = parse_key(km.resolve(L, r, c))
            if not k or not k.tapname:
                continue
            if k.kind == "shortcut":
                if k.fn == "C":
                    ctrlmap[L].setdefault(k.tapname, (r, c))
            else:
                outmap[L].setdefault(k.tapname, (r, c))
    return outmap, ctrlmap


# ------------------------------------------------- windows VK fallback ------
VK2KC = {}
for _i in range(26):
    VK2KC[0x41 + _i] = "KC_" + chr(65 + _i)
for _i in range(10):
    VK2KC[0x30 + _i] = f"KC_{_i}"
for _i in range(12):
    VK2KC[0x70 + _i] = f"KC_F{_i + 1}"
for _i in range(10):
    VK2KC[0x60 + _i] = f"KC_P{_i}"
VK2KC.update({
    0x09: "KC_TAB", 0x1B: "KC_ESC", 0x0D: "KC_ENT", 0x08: "KC_BSPC",
    0x2E: "KC_DEL", 0x20: "KC_SPC", 0x2D: "KC_INS",
    0x25: "KC_LEFT", 0x26: "KC_UP", 0x27: "KC_RGHT", 0x28: "KC_DOWN",
    0x24: "KC_HOME", 0x23: "KC_END", 0x21: "KC_PGUP", 0x22: "KC_PGDN",
    0xDE: "KC_QUOTE", 0xBC: "KC_COMMA", 0xBE: "KC_DOT", 0xBF: "KC_SLASH",
    0xBA: "KC_SCOLON", 0xBD: "KC_MINS", 0xBB: "KC_EQL", 0xDB: "KC_LBRC",
    0xDD: "KC_RBRC", 0xDC: "KC_BSLS", 0xC0: "KC_GRV",
    0xAD: "KC_MUTE", 0xAE: "KC_VOLD", 0xAF: "KC_VOLU",
    0xB0: "KC_MNXT", 0xB1: "KC_MPRV", 0xB3: "KC_MPLY",
    0x6F: "KC_PSLS", 0x6A: "KC_PAST", 0x6B: "KC_PPLS", 0x6D: "KC_PMNS",
    0x6E: "KC_PDOT",
})
SHIFT_OF = {
    "KC_GRV": "KC_TILD", "KC_1": "KC_EXLM", "KC_2": "KC_AT",
    "KC_3": "KC_HASH", "KC_4": "KC_DLR", "KC_5": "KC_PERC",
    "KC_6": "KC_CIRC", "KC_7": "KC_AMPR", "KC_8": "KC_ASTR",
    "KC_9": "KC_LPRN", "KC_0": "KC_RPRN", "KC_MINS": "KC_UNDS",
    "KC_EQL": "KC_PLUS", "KC_LBRC": "KC_LCBR", "KC_RBRC": "KC_RCBR",
    "KC_BSLS": "KC_PIPE", "KC_SCOLON": "KC_COLN", "KC_QUOTE": "KC_DQUO",
    "KC_COMMA": "KC_LT", "KC_DOT": "KC_GT", "KC_SLASH": "KC_QUES",
}
VK_MOD = {
    0x10: "Sft", 0xA0: "Sft", 0xA1: "Sft",
    0x11: "Ctl", 0xA2: "Ctl", 0xA3: "Ctl",
    0x12: "Alt", 0xA4: "Alt", 0xA5: "Alt",
    0x5B: "Win", 0x5C: "Win",
}

# ------------------------------------------------------------ vial hid ------
class VialDevice:
    def __init__(self, path: bytes):
        self.h = hid.device()
        self.h.open_path(path)
        self.h.set_nonblocking(0)
        self._flush()

    def _flush(self):
        self.h.set_nonblocking(1)
        while self.h.read(MSG_LEN):
            pass
        self.h.set_nonblocking(0)

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass

    def xfer(self, payload, expect_echo=None, tries=3) -> bytes:
        buf = bytes(payload) + b"\x00" * (MSG_LEN - len(payload))
        for _ in range(tries):
            self.h.write(b"\x00" + buf)
            resp = bytes(self.h.read(MSG_LEN, 300))
            if not resp:
                continue
            if expect_echo is None or resp[:len(expect_echo)] == bytes(expect_echo):
                return resp
        raise IOError("no/bad HID response")

    def protocol_version(self) -> int:
        r = self.xfer([0x01], expect_echo=[0x01])
        return (r[1] << 8) | r[2]

    def unlock_status(self):
        r = self.xfer([0xFE, 0x05])
        keys = []
        for i in range(2, 30, 2):
            if r[i] != 0xFF and r[i + 1] != 0xFF:
                keys.append((r[i], r[i + 1]))
        return {"unlocked": r[0] == 1, "in_progress": r[1] == 1, "keys": keys}

    def unlock_start(self):
        self.xfer([0xFE, 0x06])

    def unlock_poll(self):
        r = self.xfer([0xFE, 0x07])
        return {"unlocked": r[0] == 1, "in_progress": r[1] == 1,
                "counter": r[2]}

    def matrix_state(self, rows: int, cols: int) -> frozenset:
        bpr = (cols + 7) // 8
        r = self.xfer([0x02, 0x03], expect_echo=[0x02, 0x03])
        pressed = set()
        for row in range(rows):
            val = int.from_bytes(r[2 + row * bpr: 2 + (row + 1) * bpr], "big")
            if val:
                for col in range(cols):
                    if val & (1 << col):
                        pressed.add((row, col))
        return frozenset(pressed)


def find_raw_hid(name_filter: str = "") -> Optional[bytes]:
    if hid is None:
        return None
    for d in hid.enumerate():
        if d["usage_page"] == RAW_USAGE_PAGE and d["usage"] == RAW_USAGE:
            prod = d.get("product_string") or ""
            if name_filter and name_filter.lower() not in prod.lower():
                continue
            return d["path"]
    return None


class HidPoller(threading.Thread):
    """Polls the switch matrix; drives the Vial unlock handshake if needed."""

    def __init__(self, km: Keymap, out: queue.Queue, stop: threading.Event,
                 hz: float, name_filter: str):
        super().__init__(daemon=True, name="hid-poller")
        self.km, self.out, self.stop = km, out, stop
        self.interval = max(0.005, 1.0 / hz)
        self.name_filter = name_filter
        self.unlock_requested = threading.Event()

    def run(self):
        while not self.stop.is_set():
            path = find_raw_hid(self.name_filter)
            if not path:
                self.out.put(("mode", "disconnected"))
                self.stop.wait(2.0)
                continue
            dev = None
            try:
                dev = VialDevice(path)
                dev.protocol_version()
                if not self._ensure_unlocked(dev):
                    continue
                self.out.put(("kb_lock", None))
                self.out.put(("mode", "hid"))
                last = None
                while not self.stop.is_set():
                    m = dev.matrix_state(self.km.rows, self.km.cols)
                    if m != last:
                        last = m
                        self.out.put(("matrix", m))
                    self.stop.wait(self.interval)
            except Exception as e:
                self.out.put(("mode", "disconnected"))
                self.out.put(("log", f"HID error: {e}"))
                self.stop.wait(1.5)
            finally:
                if dev:
                    dev.close()

    def _ensure_unlocked(self, dev: VialDevice) -> bool:
        """Returns True once unlocked; False to force a reconnect cycle."""
        st = dev.unlock_status()
        if st["unlocked"]:
            return True
        self.out.put(("kb_lock", {"keys": st["keys"], "counter": -1}))
        self.out.put(("mode", "locked"))
        # Wait: either the user triggers our unlock flow (Ctrl+Alt+U),
        # or they unlock via Vial GUI and we notice.
        while not self.stop.is_set():
            if self.unlock_requested.is_set():
                self.unlock_requested.clear()
                dev.unlock_start()
                while not self.stop.is_set():
                    p = dev.unlock_poll()
                    if p["unlocked"]:
                        return True
                    self.out.put(("kb_lock", {"keys": st["keys"],
                                              "counter": p["counter"]}))
                    self.stop.wait(0.25)
                return False
            st = dev.unlock_status()
            if st["unlocked"]:
                return True
            self.stop.wait(0.6)
        return False


# ------------------------------------------------------- low level hook -----
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wt.HINSTANCE,
                                     wt.DWORD)
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = (wt.HHOOK, ctypes.c_int, wt.WPARAM,
                                  wt.LPARAM)

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD),
                ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HookThread(threading.Thread):
    """WH_KEYBOARD_LL listener; feeds ('vk', code, is_down) into the queue."""

    def __init__(self, out: queue.Queue, stop: threading.Event):
        super().__init__(daemon=True, name="kbd-hook")
        self.out, self.stop = out, stop

    def run(self):
        @HOOKPROC
        def proc(nCode, wParam, lParam):
            if nCode == 0:
                ks = ctypes.cast(lParam,
                                 ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                up = wParam in (WM_KEYUP, WM_SYSKEYUP)
                if down or up:
                    self.out.put(("vk", ks.vkCode, down))
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = proc                      # keep alive (GC guard)
        hook = user32.SetWindowsHookExW(13, proc, None, 0)
        if not hook:
            self.out.put(("log", "keyboard hook failed"))
            return
        msg = wt.MSG()
        while not self.stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
        user32.UnhookWindowsHookEx(hook)


class HotkeyThread(threading.Thread):
    """Global hotkeys: Ctrl+Alt+K lock, Ctrl+Alt+Shift+K quit, Ctrl+Alt+U unlock."""

    HK_LOCK, HK_QUIT, HK_UNLOCK = 1, 2, 3

    def __init__(self, out: queue.Queue, stop: threading.Event):
        super().__init__(daemon=True, name="hotkeys")
        self.out, self.stop = out, stop

    def run(self):
        MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 1, 2, 4, 0x4000
        regs = [
            (self.HK_LOCK, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("K")),
            (self.HK_QUIT, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
             ord("K")),
            (self.HK_UNLOCK, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("U")),
        ]
        for hk_id, mods, vk in regs:
            if not user32.RegisterHotKey(None, hk_id, mods, vk):
                self.out.put(("log", f"hotkey id {hk_id} not registered"))
        msg = wt.MSG()
        while not self.stop.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == WM_HOTKEY:
                self.out.put(("hotkey", msg.wParam))
        for hk_id, _, _ in regs:
            user32.UnregisterHotKey(None, hk_id)


# ------------------------------------------------------- window helpers -----
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

try:
    _GetWL = user32.GetWindowLongPtrW
    _SetWL = user32.SetWindowLongPtrW
except AttributeError:
    _GetWL = user32.GetWindowLongW
    _SetWL = user32.SetWindowLongW
_GetWL.restype = ctypes.c_ssize_t
_GetWL.argtypes = (wt.HWND, ctypes.c_int)
_SetWL.restype = ctypes.c_ssize_t
_SetWL.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_ssize_t)


def work_area():
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


# ------------------------------------------------------------- overlay ------
class OverlayApp:
    def __init__(self, km: Keymap, args):
        self.km = km
        self.args = args
        self.q: queue.Queue = queue.Queue()
        self.stop = threading.Event()

        self.outmap, self.ctrlmap = build_outmaps(km)

        # --- state ---
        self.source = "connecting"      # hid | hook | locked | disconnected
        self.pressed_hid: frozenset = frozenset()
        self.pressed_hook: set = set()
        self.hook_held: dict = {}       # vk -> (r, c)
        self.hook_layer = 0
        self.hook_expiry = 0.0
        self.layer_hid = 0
        self.mods: set = set()
        self.last_key = ""
        self.kb_lock_info = None        # dict when Vial-locked
        self.locked = False
        self.scale = 1.0
        self._drag = None
        self._dirty = True

        self._load_config()
        if args.scale:
            self.scale = args.scale
        if args.reset_pos:
            self._cfg_pos = None

        # --- window ---
        self.root = tk.Tk()
        self.root.title("OverlayCorne")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self.root.configure(bg=TRANSPARENT)

        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self._metrics()
        self._place_window(initial=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Lock position   (Ctrl+Alt+K)",
                              command=self.toggle_lock)
        self.menu.add_command(label="Snap bottom-right",
                              command=self._snap_bottom_right)
        self.menu.add_command(label="Scale +", command=lambda: self._rescale(+0.1))
        self.menu.add_command(label="Scale -", command=lambda: self._rescale(-0.1))
        self.menu.add_separator()
        self.menu.add_command(label="Unlock keyboard (Vial)  (Ctrl+Alt+U)",
                              command=self._request_kb_unlock)
        self.menu.add_separator()
        self.menu.add_command(label="Quit   (Ctrl+Alt+Shift+K)",
                              command=self.quit)

        # --- threads ---
        self.poller = None
        if hid is not None and not args.no_hid:
            self.poller = HidPoller(km, self.q, self.stop, args.hz,
                                    args.device)
            self.poller.start()
        else:
            self.source = "hook"
            if hid is None:
                print("hidapi not installed -> OS hook mode only "
                      "(pip install hidapi)")
        HookThread(self.q, self.stop).start()
        HotkeyThread(self.q, self.stop).start()

        self.root.after(80, self._apply_exstyles)
        self.root.after(20, self._pump)
        self.root.after(3000, self._assert_topmost)

    # ---------------- geometry / fonts ----------------
    def _metrics(self):
        s = self.scale
        self.k = int(34 * s)              # key size
        self.g = max(2, int(5 * s))       # gap
        self.inner = int(11 * s)          # extra gap around inner column
        self.pad = int(8 * s)
        self.header_h = int(26 * s)
        self.thumb_drop = int(6 * s)
        self.w = self.pad * 2 + self.km.cols * self.k \
            + (self.km.cols - 1) * self.g + 2 * self.inner
        self.h = self.pad * 2 + self.header_h + self.km.rows * self.k \
            + (self.km.rows - 1) * self.g + self.thumb_drop

        def f(size, bold=True):
            return tkfont.Font(family="Segoe UI",
                               size=-max(8, int(size * s)),
                               weight="bold" if bold else "normal")
        self.f_big = f(15)
        self.f_mid = f(11)
        self.f_small = f(9)
        self.f_hold = f(8, bold=False)
        self.f_chip = f(9)
        self.f_head = f(11)

    def _pick_font(self, text: str):
        n = len(text)
        if n <= 2:
            return self.f_big
        if n <= 3:
            return self.f_mid
        return self.f_small

    def key_rect(self, r, c):
        x = self.pad + c * (self.k + self.g)
        if c >= 6:
            x += self.inner
        if c >= 7:
            x += self.inner
        y = self.pad + self.header_h + r * (self.k + self.g)
        if r == self.km.rows - 1:
            y += self.thumb_drop
        return x, y, x + self.k, y + self.k

    def _place_window(self, initial=False):
        self.canvas.config(width=self.w, height=self.h)
        if initial and self._cfg_pos:
            x, y = self._cfg_pos
            l, t, rr, bb = work_area()
            if not (l - self.w < x < rr and t - self.h < y < bb):
                x = y = None
        else:
            x = y = None
        if x is None:
            l, t, rr, bb = work_area()
            x = rr - self.w - self.args.margin
            y = bb - self.h - self.args.margin
        self.root.geometry(f"{self.w}x{self.h}+{x}+{y}")

    def _snap_bottom_right(self):
        l, t, rr, bb = work_area()
        self.root.geometry(
            f"+{rr - self.w - self.args.margin}+{bb - self.h - self.args.margin}")
        self._save_config()

    def _rescale(self, delta):
        old_right = self.root.winfo_x() + self.w
        old_bottom = self.root.winfo_y() + self.h
        self.scale = min(2.0, max(0.7, round(self.scale + delta, 2)))
        self._metrics()
        self.canvas.config(width=self.w, height=self.h)
        self.root.geometry(
            f"{self.w}x{self.h}+{old_right - self.w}+{old_bottom - self.h}")
        self._save_config()
        self._dirty = True

    # ---------------- win32 styles ----------------
    def _hwnd(self):
        return user32.GetAncestor(self.root.winfo_id(), 2)

    def _apply_exstyles(self):
        hwnd = self._hwnd()
        style = _GetWL(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if self.locked:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        _SetWL(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10 | 0x20)

    def _assert_topmost(self):
        if self.stop.is_set():
            return
        try:
            user32.SetWindowPos(self._hwnd(), -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        except Exception:
            pass
        self.root.after(3000, self._assert_topmost)

    def toggle_lock(self):
        self.locked = not self.locked
        self._apply_exstyles()
        self._save_config()
        self._dirty = True

    # ---------------- config ----------------
    def _load_config(self):
        self._cfg_pos = None
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self._cfg_pos = (int(cfg["x"]), int(cfg["y"]))
            self.locked = bool(cfg.get("locked", False))
            self.scale = float(cfg.get("scale", 1.0))
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                           "locked": self.locked, "scale": self.scale}, f)
        except Exception:
            pass

    # ---------------- mouse ----------------
    def _on_press(self, e):
        if self.locked:
            return
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _on_motion(self, e):
        if self._drag and not self.locked:
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _on_release(self, _e):
        if self._drag:
            self._drag = None
            self._save_config()

    def _on_menu(self, e):
        if not self.locked:
            self.menu.tk_popup(e.x_root, e.y_root)

    def _request_kb_unlock(self):
        if self.poller:
            self.poller.unlock_requested.set()

    def quit(self):
        self._save_config()
        self.stop.set()
        self.root.after(60, self.root.destroy)

    # ---------------- event pump ----------------
    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        # hook layer decay
        if self.source != "hid" and self.hook_layer and \
                time.monotonic() > self.hook_expiry and not self.pressed_hook:
            self.hook_layer = 0
            self._dirty = True
        if self._dirty:
            self._dirty = False
            self._redraw()
        if not self.stop.is_set():
            self.root.after(20, self._pump)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "matrix":
            self._on_matrix(msg[1])
        elif kind == "vk":
            self._on_vk(msg[1], msg[2])
        elif kind == "mode":
            mode = msg[1]
            self.source = "hid" if mode == "hid" else \
                ("locked" if mode == "locked" else "hook")
            if self.source != "hid":
                self.pressed_hid = frozenset()
                self.layer_hid = 0
            self._dirty = True
        elif kind == "kb_lock":
            self.kb_lock_info = msg[1]
            self._dirty = True
        elif kind == "hotkey":
            if msg[1] == HotkeyThread.HK_LOCK:
                self.toggle_lock()
            elif msg[1] == HotkeyThread.HK_QUIT:
                self.quit()
            elif msg[1] == HotkeyThread.HK_UNLOCK:
                self._request_kb_unlock()
        elif kind == "log":
            print(msg[1])

    # ---------------- HID state ----------------
    def _on_matrix(self, m: frozenset):
        old = self.pressed_hid
        self.pressed_hid = m
        layer = 0
        for pos in m:
            layer = max(layer, self.km.lt_pos.get(pos, 0))
        self.layer_hid = layer
        new = m - old
        if new:
            labels = []
            for (r, c) in sorted(new):
                k = parse_key(self.km.resolve(layer, r, c))
                if k and k.tap:
                    labels.append(k.tap)
            label = "+".join(labels)
            # combo hint: full pressed set matches a combo trigger
            if len(m) >= 2:
                names = {self.km.tapname_at_base(r, c) for (r, c) in m}
                for trig, result in self.km.combos:
                    if trig <= names:
                        label = "+".join(base_label(t) for t in sorted(trig)) \
                            + "→" + (parse_key(result).tap or "?")
                        break
            if label:
                self.last_key = (f"{LAYER_NAMES.get(layer, layer)}·{label}"
                                 if layer else label)
        self._dirty = True

    # ---------------- hook state ----------------
    def _on_vk(self, vk: int, down: bool):
        if vk in VK_MOD:
            (self.mods.add if down else self.mods.discard)(VK_MOD[vk])
            self._dirty = True
            return
        if self.source == "hid":
            return
        if not down:
            pos = self.hook_held.pop(vk, None)
            if pos:
                self.pressed_hook.discard(pos)
                self._dirty = True
            return
        if vk in self.hook_held:            # autorepeat
            return
        base = VK2KC.get(vk)
        if not base:
            return
        names = []
        if "Sft" in self.mods and base in SHIFT_OF:
            names.append(SHIFT_OF[base])
        names.append(base)
        order = [self.hook_layer] + [l for l in range(4)
                                     if l != self.hook_layer]
        found = None
        if "Ctl" in self.mods:
            for L in order:
                if base in self.ctrlmap[L]:
                    found = (L, self.ctrlmap[L][base])
                    break
        if not found:
            for L in order:
                for nm in names:
                    if nm in self.outmap[L]:
                        found = (L, self.outmap[L][nm])
                        break
                if found:
                    break
        if not found:
            return
        L, pos = found
        self.hook_held[vk] = pos
        self.pressed_hook.add(pos)
        if L:
            self.hook_layer = L
            self.hook_expiry = time.monotonic() + 1.5
        k = parse_key(self.km.resolve(L, *pos))
        if k and k.tap:
            self.last_key = (f"{LAYER_NAMES.get(L, L)}·{k.tap}"
                             if L else k.tap)
        self._dirty = True

    # ---------------- drawing ----------------
    def _rrect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r,
               x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
               x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    @property
    def display_layer(self):
        return self.layer_hid if self.source == "hid" else self.hook_layer

    @property
    def pressed(self):
        return self.pressed_hid if self.source == "hid" else self.pressed_hook

    def _redraw(self):
        cv = self.canvas
        cv.delete("all")
        s = self.scale
        L = self.display_layer

        # ---- header ----
        hx0, hy0 = self.pad, self.pad
        hx1, hy1 = self.w - self.pad, self.pad + self.header_h - int(4 * s)
        self._rrect(hx0, hy0, hx1, hy1, int(6 * s), fill=PANEL, outline=EDGE)
        cy = (hy0 + hy1) // 2

        dot_color = {"hid": LIME, "hook": AMBER,
                     "locked": RED}.get(self.source, RED)
        x = hx0 + int(12 * s)
        r_dot = max(3, int(3.5 * s))
        cv.create_oval(x - r_dot, cy - r_dot, x + r_dot, cy + r_dot,
                       fill=dot_color, outline="")
        x += int(10 * s)
        src_txt = {"hid": "HID", "hook": "OS", "locked": "LKD"}.get(
            self.source, "--")
        cv.create_text(x, cy, text=src_txt, fill=DIM, font=self.f_chip,
                       anchor="w")
        x += self.f_chip.measure(src_txt) + int(10 * s)

        for ln in range(4):
            name = LAYER_NAMES.get(ln, f"L{ln}")
            wch = self.f_chip.measure(name) + int(10 * s)
            active = (ln == L)
            if active:
                self._rrect(x, hy0 + int(4 * s), x + wch, hy1 - int(4 * s),
                            int(4 * s), fill=LAYER_ACCENT[ln], outline="")
            cv.create_text(x + wch / 2, cy, text=name,
                           fill=DARK if active else DIM, font=self.f_chip)
            x += wch + int(4 * s)

        if self.mods:
            mods_txt = " ".join(sorted(self.mods))
            x += int(6 * s)
            cv.create_text(x, cy, text=mods_txt, fill=MAGENTA,
                           font=self.f_chip, anchor="w")

        rx = hx1 - int(10 * s)
        if self.locked:
            cv.create_text(rx, cy, text="LOCK", fill=AMBER,
                           font=self.f_chip, anchor="e")
            rx -= self.f_chip.measure("LOCK") + int(10 * s)
        if self.last_key:
            cv.create_text(rx, cy, text=self.last_key, fill=INK,
                           font=self.f_head, anchor="e")

        # ---- keys ----
        pressed = self.pressed
        unlock_keys = set()
        if self.kb_lock_info:
            unlock_keys = set(map(tuple, self.kb_lock_info.get("keys", [])))

        for (r, c) in self.km.positions:
            kc = self.km.resolve(L, r, c)
            k = parse_key(kc)
            if k is None:
                continue
            trns = self.km.is_trns(L, r, c) and L != 0
            x0, y0, x1, y1 = self.key_rect(r, c)
            is_down = (r, c) in pressed
            is_layer_key = k.kind == "layer"

            if is_down:
                fill = MAGENTA if is_layer_key else AMBER
                outline = fill
                tap_fill = hold_fill = DARK
            else:
                fill = KEY_BG_LAYER if is_layer_key else KEY_BG
                outline = MAGENTA if is_layer_key else EDGE
                if trns:
                    tap_fill = DIM
                elif is_layer_key:
                    tap_fill = MAGENTA
                elif k.kind == "shortcut":
                    tap_fill = AMBER if L == 0 else LAYER_ACCENT[L]
                elif L == 0 and k.tap in ("Mute", "Del", "Boot"):
                    tap_fill = AMBER
                else:
                    tap_fill = LAYER_ACCENT[L]
                hold_fill = MAGENTA
            if (r, c) in unlock_keys and self.source == "locked":
                outline = RED

            self._rrect(x0, y0, x1, y1, int(6 * s), fill=fill,
                        outline=outline)
            cx = (x0 + x1) / 2
            if k.hold:
                cv.create_text(cx, y0 + (y1 - y0) * 0.40, text=k.tap,
                               fill=tap_fill, font=self._pick_font(k.tap))
                cv.create_text(cx, y1 - int(7 * s), text=k.hold,
                               fill=hold_fill, font=self.f_hold)
            else:
                cv.create_text(cx, (y0 + y1) / 2, text=k.tap, fill=tap_fill,
                               font=self._pick_font(k.tap))

        # ---- vial-locked banner ----
        if self.source == "locked":
            bx0, by0 = self.pad + int(20 * s), self.h // 2 - int(24 * s)
            bx1, by1 = self.w - self.pad - int(20 * s), self.h // 2 + int(24 * s)
            self._rrect(bx0, by0, bx1, by1, int(8 * s), fill=PANEL,
                        outline=RED)
            info = self.kb_lock_info or {}
            counter = info.get("counter", -1)
            line1 = "Keyboard is Vial-locked — matrix mode unavailable"
            line2 = ("Hold the highlighted keys… (%d)" % counter
                     if counter >= 0 else
                     "Press Ctrl+Alt+U, then hold the highlighted keys")
            cv.create_text((bx0 + bx1) / 2, (by0 + by1) / 2 - int(9 * s),
                           text=line1, fill=INK, font=self.f_small)
            cv.create_text((bx0 + bx1) / 2, (by0 + by1) / 2 + int(9 * s),
                           text=line2, fill=AMBER, font=self.f_small)

    def run(self):
        self.root.mainloop()
        self.stop.set()


# ---------------------------------------------------------------- main ------
def main():
    ap = argparse.ArgumentParser(description="Vial Corne keyboard overlay")
    ap.add_argument("--vil", default=DEFAULT_VIL, help="path to .vil keymap")
    ap.add_argument("--scale", type=float, default=None,
                    help="UI scale (0.7-2.0)")
    ap.add_argument("--margin", type=int, default=14,
                    help="margin from screen edge when snapping")
    ap.add_argument("--hz", type=float, default=60,
                    help="matrix poll rate")
    ap.add_argument("--device", default="",
                    help="substring filter for HID product name")
    ap.add_argument("--no-hid", action="store_true",
                    help="skip HID, OS hook mode only")
    ap.add_argument("--reset-pos", action="store_true",
                    help="ignore saved position, snap bottom-right")
    ap.add_argument("--list", action="store_true",
                    help="list raw HID devices and exit")
    args = ap.parse_args()

    if args.list:
        if hid is None:
            print("hidapi not installed")
            return
        for d in hid.enumerate():
            if d["usage_page"] == RAW_USAGE_PAGE and d["usage"] == RAW_USAGE:
                print(f"{d['product_string']}  vid={d['vendor_id']:#06x} "
                      f"pid={d['product_id']:#06x}")
        return

    if not os.path.exists(args.vil):
        print(f"keymap not found: {args.vil}")
        sys.exit(1)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    km = Keymap(args.vil)
    app = OverlayApp(km, args)
    app.run()
    os._exit(0)


if __name__ == "__main__":
    main()
