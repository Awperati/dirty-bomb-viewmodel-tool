"""
Dirty Bomb viewmodel position tool.

A small hook records which weapon you are holding each frame; this tool then
adds your offset to that weapon's m_PlayerViewOffset (forward / right / up).
The weapon's original offset is put back when you switch weapons, toggle off
or close this window. Can run alongside viewmodel_fov.py.

OFFLINE USE ONLY. Dirty Bomb ships with EasyAntiCheat. Patching game memory
while playing online can get you kicked or banned.

Hotkeys (numpad, Num Lock on; work while the game is focused):
  Num5        toggle on/off
  Num4 / Num6 move left / right
  Num8 / Num2 move up / down
  Num7 / Num9 move closer / further
  Num0        reset offset to 0
  Ctrl+C in this window, or closing it, unhooks and exits.
"""
import struct, sys, time, atexit, threading
import dbmem

SETTINGS_FILE = "position_settings.json"
DEFAULTS = {"right": 4.0, "down": 2.0, "forward": 0.0, "enabled": True}
STEP = 0.25
LIMIT = 30.0
KEYS = {0x65: "toggle", 0x64: "left", 0x66: "right", 0x68: "up", 0x62: "down",
        0x67: "closer", 0x69: "further", 0x60: "reset"}

VIEW_OFFSET = 0x868       # SGWeapon.m_PlayerViewOffset (FVector)
WEAPON_FOV = 0x890        # SGWeapon.m_WeaponFOV, used as a sanity check

PATTERN = dbmem.SITE_PATTERN
HOOK_OFFSET = dbmem.POSITION_HOOK_OFFSET
ORIGINAL = bytes.fromhex("48 8B 83 34 1E 00 00 8B 88 80 13 00 00")   # mov rax,[rbx+1E34]; mov ecx,[rax+1380]

def build_cave(cave, hook):
    code = bytearray()
    code += bytes.fromhex("48 8B 83 34 1E 00 00")       # mov rax,[rbx+1E34]  (original: current weapon)
    st_at = len(code); code += bytes.fromhex("48 89 05 00 00 00 00")   # mov [rip+weapon],rax
    code += bytes.fromhex("8B 88 80 13 00 00")          # mov ecx,[rax+1380]  (original)
    jmp_at = len(code); code += bytes.fromhex("E9 00 00 00 00")        # jmp back
    while len(code) % 16:
        code += b"\xCC"
    weapon_at = len(code); code += bytes(8)
    struct.pack_into("<i", code, st_at + 3, weapon_at - (st_at + 7))
    struct.pack_into("<i", code, jmp_at + 1, (hook + len(ORIGINAL)) - (cave + jmp_at + 5))
    return bytes(code), {"weapon": weapon_at}

def read_vec(h, addr):
    b = dbmem.rpm(h, addr, 12)
    return struct.unpack("<3f", b) if b and len(b) == 12 else None

def looks_like_weapon(h, w):
    b = dbmem.rpm(h, w + WEAPON_FOV, 4)
    return b is not None and len(b) == 4 and 5.0 < struct.unpack("<f", b)[0] < 170.0

class Offsetter:
    def __init__(self, hook, s):
        self.hook, self.s = hook, s
        self.weapon = None      # weapon we modified
        self.orig = None        # its original offset
        self.written = None     # bytes we wrote
        # The window-close handler runs on another thread while the main loop keeps
        # ticking; the lock + flag stop the loop from re-applying after we restore.
        self.lock = threading.Lock()
        self.stopped = False

    def stop(self):
        with self.lock:
            self.stopped = True
            if self.hook.h and dbmem.alive(self.hook.h):
                self.restore()

    def delta(self):
        return (self.s["forward"], self.s["right"], -self.s["down"])

    def restore(self):
        h, w = self.hook.h, self.weapon
        if w and self.written and dbmem.rpm(h, w + VIEW_OFFSET, 12) == self.written:
            dbmem.wpm(h, w + VIEW_OFFSET, struct.pack("<3f", *self.orig))
        self.weapon = self.orig = self.written = None

    def apply(self, w):
        h = self.hook.h
        if w != self.weapon:
            self.restore()
            v = read_vec(h, w + VIEW_OFFSET)
            if v is None:
                return
            self.weapon, self.orig = w, v
        new = struct.pack("<3f", *(o + d for o, d in zip(self.orig, self.delta())))
        dbmem.wpm(h, w + VIEW_OFFSET, new)
        self.written = new

    def tick(self, force=False):
        with self.lock:
            if not self.stopped:
                self._tick(force)

    def _tick(self, force):
        h = self.hook.h
        raw = dbmem.rpm(h, self.hook.vars["weapon"], 8)
        w = struct.unpack("<Q", raw)[0] if raw else 0
        if w:
            dbmem.wpm(h, self.hook.vars["weapon"], bytes(8))   # hook refreshes it every frame
        if not self.s["enabled"]:
            self.restore(); return
        if not w or not looks_like_weapon(h, w):
            return
        if w == self.weapon and dbmem.rpm(h, w + VIEW_OFFSET, 12) != self.written:
            # the game reset this weapon's offset (respawn / object reuse): start fresh
            self.weapon = self.orig = self.written = None
        if force or w != self.weapon:
            self.apply(w)

def status(s):
    sys.stdout.write(f"\r  [POS {'ON ' if s['enabled'] else 'OFF'}]  right {s['right']:+.2f}  "
                     f"down {s['down']:+.2f}  forward {s['forward']:+.2f}   "
                     f"Num5 toggle  Num4/6 Num8/2 Num7/9  Num0 reset      ")
    sys.stdout.flush()

def main():
    print(__doc__)
    dbmem.single_instance("Position")
    s = dbmem.load_settings(SETTINGS_FILE, DEFAULTS)
    hook = dbmem.CodeHook(PATTERN, HOOK_OFFSET, ORIGINAL, build_cave)
    off = Offsetter(hook, s)

    def shutdown():
        try:
            off.stop()
        finally:
            hook.detach()
    atexit.register(shutdown)
    dbmem.on_console_close(shutdown)

    try:
        while True:
            pid = dbmem.wait_for_game()
            try:
                hook.attach(pid)
            except Exception as e:
                print(f"\n  Could not hook: {e}"); hook.detach(); time.sleep(5); continue
            print("\n  Hooked.")
            status(s)
            while dbmem.alive(hook.h):
                changed = None
                for vk, action in KEYS.items():
                    if dbmem.pressed(vk):
                        changed = action
                        if action == "toggle":  s["enabled"] = not s["enabled"]
                        elif action == "left":  s["right"] -= STEP
                        elif action == "right": s["right"] += STEP
                        elif action == "up":    s["down"] -= STEP
                        elif action == "down":  s["down"] += STEP
                        elif action == "closer":  s["forward"] -= STEP
                        elif action == "further": s["forward"] += STEP
                        elif action == "reset": s.update(right=0.0, down=0.0, forward=0.0)
                for k in ("right", "down", "forward"):
                    s[k] = round(max(-LIMIT, min(LIMIT, s[k])), 2)
                try:
                    off.tick(force=changed is not None)
                except OSError:
                    pass
                if changed:
                    status(s); dbmem.save_settings(SETTINGS_FILE, s)
                time.sleep(0.03)
            print("\n  Game closed.")
            off.weapon = off.orig = off.written = None
            hook.detach()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
        print("\n  Unhooked. Bye.")

if __name__ == "__main__":
    main()
