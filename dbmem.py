"""Shared process/memory helpers for the Dirty Bomb viewmodel tools."""
import ctypes, ctypes.wintypes as wt, json, os, sys, time

PROCESS_NAME = "shootergame-win32-shipping.exe"

# Camera update code both tools hook. Both patch regions are wildcarded so either
# tool still finds the site when the other one (or a stale hook) has patched it.
#   +00  mov rax,[rax+1E34]; test rax,rax; je ??
#   +12  mov eax,[rax+890]; mov [rsi+CF0],eax          <- FOV hook (12 bytes)
#   +24  mov rax,[rbx+1E34]; mov ecx,[rax+1380]         <- position hook (13 bytes)
#   +37  mov [rsi+CF4],ecx; mov rax,[rbx+1E34]; mov ecx,[rax+1384]; mov [rsi+CF8],ecx
SITE_PATTERN = ("48 8B 80 34 1E 00 00 48 85 C0 74 ?? " + "?? " * 12 + "?? " * 13 +
                "89 8E F4 0C 00 00 48 8B 83 34 1E 00 00 8B 88 84 13 00 00 89 8E F8 0C 00 00")
FOV_HOOK_OFFSET = 12
POSITION_HOOK_OFFSET = 24

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32")
PROCESS_ACCESS = 0x0010 | 0x0020 | 0x0008 | 0x0400   # VM_READ|VM_WRITE|VM_OPERATION|QUERY_INFO
MEM_COMMIT_RESERVE, MEM_RELEASE, PAGE_RWX = 0x3000, 0x8000, 0x40
TH32CS_SNAPPROCESS, TH32CS_SNAPMODULE = 0x2, 0x8 | 0x10
STILL_ACTIVE = 259

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]

class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
                ("hModule", wt.HMODULE), ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]

k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.FlushInstructionCache.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CloseHandle.argtypes = [wt.HANDLE]

def find_pid():
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32W(); e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    try:
        while ok:
            if e.szExeFile.lower() == PROCESS_NAME:
                return e.th32ProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None

def main_module(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    e = MODULEENTRY32W(); e.dwSize = ctypes.sizeof(e)
    ok = k32.Module32FirstW(snap, ctypes.byref(e))
    try:
        while ok:
            if e.szModule.lower() == PROCESS_NAME:
                return e.modBaseAddr, e.modBaseSize
            ok = k32.Module32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    raise RuntimeError("game module not found")

def open_process(pid):
    h = k32.OpenProcess(PROCESS_ACCESS, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    return h

def alive(h):
    code = wt.DWORD()
    return bool(h) and bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE

def rpm(h, addr, n):
    buf = ctypes.create_string_buffer(n); got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]

def wpm(h, addr, data, code=False):
    old = wt.DWORD()
    if code:
        k32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), PAGE_RWX, ctypes.byref(old))
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), None)
    if code:
        k32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(addr), len(data))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

def aob_scan(h, base, size, pattern):
    parts = pattern.split()
    needle = bytes(0 if p == "??" else int(p, 16) for p in parts)
    mask = [p != "??" for p in parts]
    first = needle[:mask.index(False)] if False in mask else needle   # fixed prefix for fast find
    hits, chunk = [], 0x100000
    for off in range(0, size, chunk):
        data = rpm(h, base + off, min(chunk + len(parts), size - off))
        if not data:
            continue
        i = data.find(first)
        while i != -1 and i + len(parts) <= len(data):
            if all(not m or data[i + j] == needle[j] for j, m in enumerate(mask)):
                hits.append(base + off + i)
            i = data.find(first, i + 1)
    return sorted(set(hits))

def alloc_near(h, target, size=0x1000):
    # rel32 jumps need the cave within +-2GB of the hook
    for delta in range(0x10000, 0x7FF00000, 0x10000):
        for addr in (target - delta, target + delta):
            if addr <= 0:
                continue
            p = k32.VirtualAllocEx(h, ctypes.c_void_p(addr & ~0xFFFF), size, MEM_COMMIT_RESERVE, PAGE_RWX)
            if p:
                return p
    raise RuntimeError("could not allocate code cave near the game module")

class CodeHook:
    """Replace `original` bytes at the unique match of `pattern` (+offset) with a jmp to a cave.

    build(cave_addr, hook_addr) must return (cave_bytes, {name: offset_in_cave}).
    """
    def __init__(self, pattern, offset, original, build):
        self.pattern, self.offset, self.original, self.build = pattern, offset, original, build
        self.h = self.cave = self.hook = None
        self.vars = {}

    def attach(self, pid):
        self.h = open_process(pid)
        base, size = main_module(pid)
        hits = aob_scan(self.h, base, size, self.pattern)
        if len(hits) != 1:
            raise RuntimeError(f"expected 1 pattern match, found {len(hits)} (game updated?)")
        self.hook = hits[0] + self.offset
        cur = rpm(self.h, self.hook, len(self.original))
        if cur != self.original:
            self._clear_stale_hook(cur)
        self.cave = alloc_near(self.h, self.hook)
        code, offsets = self.build(self.cave, self.hook)
        self.vars = {k: self.cave + v for k, v in offsets.items()}
        wpm(self.h, self.cave, code)
        rel = self.cave - (self.hook + 5)
        patch = b"\xE9" + rel.to_bytes(4, "little", signed=True) + b"\x90" * (len(self.original) - 5)
        wpm(self.h, self.hook, patch, code=True)

    def _clear_stale_hook(self, cur):
        # A previous run that was killed without unhooking leaves "jmp cave" here, and
        # its cave starts with the same instruction we displaced. Put the original back.
        if cur and cur[0] == 0xE9:
            target = self.hook + 5 + int.from_bytes(cur[1:5], "little", signed=True)
            head = rpm(self.h, target, 6)
            if head and head == self.original[:6]:
                wpm(self.h, self.hook, self.original, code=True)
                time.sleep(0.1)
                if rpm(self.h, self.hook, len(self.original)) == self.original:
                    print("\n  Removed a hook left behind by an earlier run.")
                    return
        raise RuntimeError("hook site already modified (is another copy of this tool running?)")

    def detach(self):
        if not self.h:
            return
        if alive(self.h):
            try:
                wpm(self.h, self.hook, self.original, code=True)
                time.sleep(0.1)   # let any thread inside the cave finish before freeing it
                k32.VirtualFreeEx(self.h, ctypes.c_void_p(self.cave), 0, MEM_RELEASE)
            except OSError:
                pass
        k32.CloseHandle(self.h)
        self.h = None

k32.CreateMutexW.restype = wt.HANDLE
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
ERROR_ALREADY_EXISTS = 183
_mutex = None

def single_instance(name):
    """Exit if another copy of this tool is already running."""
    global _mutex
    _mutex = k32.CreateMutexW(None, False, f"Local\\DirtyBombViewmodel_{name}")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        print(f"\n  {name} tool is already running in another window.")
        time.sleep(4)
        sys.exit(0)

_HandlerType = ctypes.WINFUNCTYPE(wt.BOOL, wt.DWORD)
_handler_ref = None

def on_console_close(cleanup):
    """Run cleanup when the window is closed (X button), logged off or shut down.

    Windows gives the process about 5 seconds, which is plenty to unhook.
    """
    global _handler_ref
    def handler(event):
        if event in (2, 5, 6):   # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
            try:
                cleanup()
            finally:
                os._exit(0)
        return False             # let Ctrl+C raise KeyboardInterrupt as usual
    _handler_ref = _HandlerType(handler)
    k32.SetConsoleCtrlHandler(_handler_ref, True)

def pressed(vk, _state={}):
    down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
    was = _state.get(vk, False); _state[vk] = down
    return down and not was

# Where settings files live; the packaged GUI exe points this at %APPDATA% instead.
SETTINGS_DIR = os.path.dirname(os.path.abspath(__file__))

def load_settings(name, defaults):
    path = os.path.join(SETTINGS_DIR, name)
    try:
        with open(path) as f:
            return {**defaults, **json.load(f)}
    except (OSError, ValueError):
        return dict(defaults)

def save_settings(name, values):
    path = os.path.join(SETTINGS_DIR, name)
    try:
        with open(path, "w") as f:
            json.dump(values, f, indent=2)
    except OSError:
        pass

def wait_for_game(msg="Waiting for Dirty Bomb to start..."):
    while True:
        pid = find_pid()
        if pid:
            time.sleep(3)   # give the game a moment to finish loading its code
            return pid
        sys.stdout.write(f"\r  {msg}                              "); sys.stdout.flush()
        time.sleep(2)
