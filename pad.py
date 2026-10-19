"""Virtual Xbox 360 pads via ViGEmBus, with a safe test-mode fallback.

Each connected phone claims one slot (0..3). With the ViGEmBus driver
installed, a slot is a real virtual Xbox 360 controller that any game can
see. Without the driver, slots still accept input ("test mode") so the
whole pipeline can be exercised on the status page before installing
anything.
"""

import time

MAX_SLOTS = 4

try:
    import vgamepad as vg
    _IMPORT_ERROR = None
except Exception as e:  # bundled DLL failed to load
    vg = None
    _IMPORT_ERROR = e

if vg is not None:
    _BUTTONS = {
        "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        "back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
        "ls": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
        "rs": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        "up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    }


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, v))


class Slot:
    def __init__(self, index, pad):
        self.index = index
        self.pad = pad          # vgamepad VX360Gamepad, or None in test mode
        self.ip = None
        self.connected_at = time.time()
        self.last_seen = self.connected_at
        self.msg_count = 0
        self.state = {"btn": {}, "lx": 0, "ly": 0, "rx": 0, "ry": 0, "lt": 0, "rt": 0}

    def apply(self, s):
        self.state = s
        self.last_seen = time.time()
        self.msg_count += 1
        p = self.pad
        if p is None:
            return
        btn = s.get("btn") or {}
        for name, flag in _BUTTONS.items():
            if btn.get(name):
                p.press_button(flag)
            else:
                p.release_button(flag)
        p.left_joystick_float(_clamp(s.get("lx"), -1, 1), _clamp(s.get("ly"), -1, 1))
        p.right_joystick_float(_clamp(s.get("rx"), -1, 1), _clamp(s.get("ry"), -1, 1))
        p.left_trigger_float(_clamp(s.get("lt"), 0, 1))
        p.right_trigger_float(_clamp(s.get("rt"), 0, 1))
        p.update()

    def neutral(self):
        self.apply({"btn": {}, "lx": 0, "ly": 0, "rx": 0, "ry": 0, "lt": 0, "rt": 0})


class PadManager:
    def __init__(self):
        self.slots = [None] * MAX_SLOTS
        self.mode = "vigem" if vg is not None else "mock"
        self.error = str(_IMPORT_ERROR) if _IMPORT_ERROR else None
        if vg is not None:  # probe the driver now so the status page is honest
            try:
                probe = vg.VX360Gamepad()
                del probe
            except Exception as e:
                self.mode = "mock"
                self.error = str(e)

    def claim(self):
        for i in range(MAX_SLOTS):
            if self.slots[i] is None:
                pad = None
                if vg is not None:
                    try:
                        pad = vg.VX360Gamepad()
                        self.mode = "vigem"
                    except Exception as e:  # driver not installed
                        self.mode = "mock"
                        self.error = str(e)
                slot = Slot(i, pad)
                self.slots[i] = slot
                return slot
        return None

    def release(self, slot):
        if slot is None:
            return
        try:
            slot.neutral()
        except Exception:
            pass
        slot.pad = None  # vgamepad unplugs the virtual pad on garbage collection
        if self.slots[slot.index] is slot:
            self.slots[slot.index] = None

    def status(self):
        now = time.time()
        return {
            "mode": self.mode,
            "error": self.error,
            "slots": [
                None if s is None else {
                    "player": s.index + 1,
                    "ip": s.ip,
                    "connected_s": round(now - s.connected_at),
                    "idle_s": round(now - s.last_seen, 1),
                    "messages": s.msg_count,
                    "state": s.state,
                }
                for s in self.slots
            ],
        }
