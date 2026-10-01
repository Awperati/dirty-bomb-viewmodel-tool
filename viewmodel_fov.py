"""
Dirty Bomb viewmodel FOV tool.

Hooks the instruction that copies the equipped weapon's m_WeaponFOV into the
camera every frame, and multiplies it while enabled. Nothing is written to
weapon data or game files; turning it off (or closing this window) restores
the original code. Can run alongside viewmodel_position.py.

OFFLINE USE ONLY. Dirty Bomb ships with EasyAntiCheat. Patching game memory
while playing online can get you kicked or banned.

Hotkeys (work while the game is focused):
  F7  toggle on/off
  F8  smaller change  (scale - step)
  F9  bigger change   (scale + step)
  Ctrl+C in this window, or closing it, unhooks and exits.
"""
import struct, sys, time, atexit
import dbmem

SETTINGS_FILE = "fov_settings.json"
DEFAULTS = {"scale": 1.5, "enabled": True}   # 52 (default rifle) * 1.5 = 78
STEP = 0.05
MIN_SCALE, MAX_SCALE = 0.5, 3.0
KEY_TOGGLE, KEY_DOWN, KEY_UP = 0x76, 0x77, 0x78   # F7, F8, F9

PATTERN = dbmem.SITE_PATTERN
HOOK_OFFSET = dbmem.FOV_HOOK_OFFSET
ORIGINAL = bytes.fromhex("8B 80 90 08 00 00 89 86 F0 0C 00 00")   # mov eax,[rax+890]; mov [rsi+CF0],eax

def build_cave(cave, hook):
    code = bytearray()
    code += bytes.fromhex("8B 80 90 08 00 00")          # mov eax,[rax+890]   (original)
    cmp_at = len(code); code += bytes.fromhex("80 3D 00 00 00 00 00")   # cmp byte [rip+enabled],0
    je_at = len(code); code += bytes.fromhex("74 00")   # je store
    code += bytes.fromhex("48 83 EC 10")                # sub rsp,10
    code += bytes.fromhex("F3 0F 7F 04 24")             # movdqu [rsp],xmm0
    code += bytes.fromhex("66 0F 6E C0")                # movd xmm0,eax
    mul_at = len(code); code += bytes.fromhex("F3 0F 59 05 00 00 00 00")  # mulss xmm0,[rip+scale]
    code += bytes.fromhex("66 0F 7E C0")                # movd eax,xmm0
    code += bytes.fromhex("F3 0F 6F 04 24")             # movdqu xmm0,[rsp]
    code += bytes.fromhex("48 83 C4 10")                # add rsp,10
    store_at = len(code)
    code += bytes.fromhex("89 86 F0 0C 00 00")          # mov [rsi+CF0],eax   (original)
    jmp_at = len(code); code += bytes.fromhex("E9 00 00 00 00")  # jmp back
    while len(code) % 16:
        code += b"\xCC"
    enabled_at = len(code); code += b"\x00\x00\x00\x00"
    scale_at = len(code); code += struct.pack("<f", 1.0)

    code[je_at + 1] = store_at - (je_at + 2)
    struct.pack_into("<i", code, cmp_at + 2, enabled_at - (cmp_at + 7))
    struct.pack_into("<i", code, mul_at + 4, scale_at - (mul_at + 8))
    struct.pack_into("<i", code, jmp_at + 1, (hook + len(ORIGINAL)) - (cave + jmp_at + 5))
    return bytes(code), {"enabled": enabled_at, "scale": scale_at}

def status(s):
    sys.stdout.write(f"\r  [FOV {'ON ' if s['enabled'] else 'OFF'}]  scale x{s['scale']:.2f}  "
                     f"(rifle 52 -> {52 * s['scale']:.0f})   F7 toggle  F8/F9 -/+      ")
    sys.stdout.flush()

def main():
    print(__doc__)
    dbmem.single_instance("FOV")
    s = dbmem.load_settings(SETTINGS_FILE, DEFAULTS)
    hook = dbmem.CodeHook(PATTERN, HOOK_OFFSET, ORIGINAL, build_cave)
    atexit.register(hook.detach)
    dbmem.on_console_close(hook.detach)

    def push():
        dbmem.wpm(hook.h, hook.vars["scale"], struct.pack("<f", s["scale"]))
        dbmem.wpm(hook.h, hook.vars["enabled"], b"\x01" if s["enabled"] else b"\x00")

    try:
        while True:
            pid = dbmem.wait_for_game()
            try:
                hook.attach(pid)
            except Exception as e:
                print(f"\n  Could not hook: {e}"); hook.detach(); time.sleep(5); continue
            push()
            print("\n  Hooked.")
            status(s)
            while dbmem.alive(hook.h):
                changed = False
                if dbmem.pressed(KEY_TOGGLE):
                    s["enabled"] = not s["enabled"]; changed = True
                if dbmem.pressed(KEY_DOWN):
                    s["scale"] = max(MIN_SCALE, round(s["scale"] - STEP, 2)); changed = True
                if dbmem.pressed(KEY_UP):
                    s["scale"] = min(MAX_SCALE, round(s["scale"] + STEP, 2)); changed = True
                if changed:
                    push(); status(s); dbmem.save_settings(SETTINGS_FILE, s)
                time.sleep(0.02)
            print("\n  Game closed.")
            hook.detach()
    except KeyboardInterrupt:
        pass
    finally:
        hook.detach()
        print("\n  Unhooked. Bye.")

if __name__ == "__main__":
    main()
