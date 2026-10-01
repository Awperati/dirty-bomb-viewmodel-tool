"""
Dirty Bomb Viewmodel Tool - GUI edition.

One window for both tools: live sliders, +/- buttons and toggles for the viewmodel
FOV multiplier and position. It reuses the hook code from the parent folder
(dbmem.py, viewmodel_fov.py, viewmodel_position.py), so the in-game hotkeys
(F7/F8/F9 and the numpad) keep working while this window is open.

OFFLINE USE ONLY. Dirty Bomb ships with EasyAntiCheat; patching game memory
while it is running can get you kicked or banned.

Pure standard library (tkinter + ctypes). Needs Windows and Python 3.8+.
"""
import atexit, ctypes, ctypes.wintypes as wt, json, math, os, queue, struct, sys, threading, time, winreg
import tkinter as tk
from tkinter import font as tkfont, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dbmem
import viewmodel_fov as fovmod
import viewmodel_position as posmod

FROZEN = getattr(sys, "frozen", False)          # running as the packaged .exe
RES = getattr(sys, "_MEIPASS", HERE)            # where bundled files (icon) live
if FROZEN:   # the exe unpacks to a temp folder each run, so keep settings somewhere permanent
    DATA_DIR = os.path.join(os.environ.get("APPDATA", HERE), "DirtyBombViewmodelTool")
    os.makedirs(DATA_DIR, exist_ok=True)
    dbmem.SETTINGS_DIR = DATA_DIR
else:
    DATA_DIR = HERE
CONFIG_FILE = os.path.join(DATA_DIR, "gui_config.json")
ICON = os.path.join(RES, "assets", "icon.ico")
CONFIG_DEFAULTS = {"accepted": False, "tray": True}

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return {**CONFIG_DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(CONFIG_DEFAULTS)

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass

# "Start with Windows" = a per-user Run key (no admin needed); the entry launches us minimised.
RUN_KEY, RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "DirtyBombViewmodelTool"

def startup_command():
    if FROZEN:
        return f'"{sys.executable}" --tray'
    pw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pw if os.path.exists(pw) else sys.executable}" "{os.path.abspath(__file__)}" --tray'

def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, RUN_NAME)[0])
    except OSError:
        return False

def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass

BG, CARD, CARD2, LINE = "#0e1014", "#161a21", "#1f242e", "#2b3140"
TEXT, MUTED = "#e8eaf0", "#8b93a5"
ACCENT, OK, WARN, BAD = "#ff7a1a", "#3ddc84", "#ffc233", "#ff5252"

SCALE = 1.0
F = {}

def px(n):
    return int(round(n * SCALE))

def blend(a, b, t):
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))

def dark_titlebar(win):
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):   # immersive dark mode (Win10 20H1+ / older builds)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4)
        caption = ctypes.c_int(0x00141010)   # COLORREF 0x00BBGGRR (Win11 caption colour)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
    except Exception:
        pass

# ---------------------------------------------------------------- engine ---

FOV_KEYS = {0x76: "toggle", 0x77: "down", 0x78: "up"}

class Engine(threading.Thread):
    """Owns both hooks and polls hotkeys; talks to the UI through a queue."""

    def __init__(self, fov_s, pos_s, events):
        super().__init__(daemon=True)
        self.fov_s, self.pos_s, self.events = fov_s, pos_s, events
        self.fov = dbmem.CodeHook(fovmod.PATTERN, fovmod.HOOK_OFFSET, fovmod.ORIGINAL, fovmod.build_cave)
        self.pos = dbmem.CodeHook(posmod.PATTERN, posmod.HOOK_OFFSET, posmod.ORIGINAL, posmod.build_cave)
        self.off = posmod.Offsetter(self.pos, pos_s)
        self.stop_evt = threading.Event()
        self.fov_dirty, self.pos_dirty = threading.Event(), threading.Event()
        self.fov_ok = self.pos_ok = False

    def emit(self, *msg):
        self.events.put(msg)

    # called from the UI thread
    def touch_fov(self): self.fov_dirty.set()
    def touch_pos(self): self.pos_dirty.set()

    def stop(self):
        self.stop_evt.set()
        if self.is_alive():
            self.join(4)

    def run(self):
        try:
            while not self.stop_evt.is_set():
                pid = dbmem.find_pid()
                if not pid:
                    self.emit("state", "waiting")
                    self.stop_evt.wait(0.7)
                    continue
                self.emit("state", "loading")
                if self.stop_evt.wait(3):    # let the game finish loading its code
                    break
                if dbmem.find_pid() != pid:
                    continue
                self.attach(pid)
                if self.fov_ok or self.pos_ok:
                    self.session()
                    self.emit("log", "Game closed.")
                else:
                    self.stop_evt.wait(5)    # retry after a pause
                self.fov_ok = self.pos_ok = False
                self.off.weapon = self.off.orig = self.off.written = None
                self.pos.detach()
                self.fov.detach()
        except Exception as e:
            self.emit("log", f"Engine error: {e!r}")
        finally:
            self.off.stop()
            self.pos.detach()
            self.fov.detach()

    def attach(self, pid):
        res = []
        for hook in (self.fov, self.pos):
            try:
                hook.attach(pid)
                res += [True, ""]
            except Exception as e:
                if hook.h:   # failed before patching: just drop the handle, never "restore"
                    dbmem.k32.CloseHandle(hook.h); hook.h = None
                res += [False, str(e)]
        self.fov_ok, self.pos_ok = res[0], res[2]
        self.push_fov()
        self.emit("hooks", *res)

    def push_fov(self):
        s = self.fov_s
        if self.fov_ok:
            try:
                dbmem.wpm(self.fov.h, self.fov.vars["scale"], struct.pack("<f", s["scale"]))
                dbmem.wpm(self.fov.h, self.fov.vars["enabled"], b"\x01" if s["enabled"] else b"\x00")
            except OSError:
                pass

    def hotkeys(self):
        fs, ps = self.fov_s, self.pos_s
        cf = cp = False
        for vk, a in FOV_KEYS.items():
            if dbmem.pressed(vk):
                if a == "toggle":   fs["enabled"] = not fs["enabled"]
                elif a == "down":   fs["scale"] = max(fovmod.MIN_SCALE, round(fs["scale"] - fovmod.STEP, 2))
                else:               fs["scale"] = min(fovmod.MAX_SCALE, round(fs["scale"] + fovmod.STEP, 2))
                cf = True
        for vk, a in posmod.KEYS.items():
            if dbmem.pressed(vk):
                st = posmod.STEP
                if a == "toggle":    ps["enabled"] = not ps["enabled"]
                elif a == "left":    ps["right"] -= st
                elif a == "right":   ps["right"] += st
                elif a == "up":      ps["down"] -= st
                elif a == "down":    ps["down"] += st
                elif a == "closer":  ps["forward"] -= st
                elif a == "further": ps["forward"] += st
                elif a == "reset":   ps.update(right=0.0, down=0.0, forward=0.0)
                cp = True
        for k in ("right", "down", "forward"):
            ps[k] = round(max(-posmod.LIMIT, min(posmod.LIMIT, ps[k])), 2)
        return cf, cp

    def session(self):
        while not self.stop_evt.is_set():
            alive = (self.fov_ok and dbmem.alive(self.fov.h)) or (self.pos_ok and dbmem.alive(self.pos.h))
            if not alive:
                return
            cf, cp = self.hotkeys()
            if cf or cp:
                self.emit("sync")
            if cf or self.fov_dirty.is_set():
                self.fov_dirty.clear(); self.push_fov()
            force = cp or self.pos_dirty.is_set()
            self.pos_dirty.clear()
            if self.pos_ok:
                try:
                    self.off.tick(force=force)
                except OSError:
                    pass
            self.stop_evt.wait(0.025)

# ------------------------------------------------------------------ tray ---

class Tray(threading.Thread):
    """Notification-area icon (plain ctypes, no dependencies) with a right-click menu.

    Runs its own message loop; actions are handed to the UI through post(name).
    """
    CALLBACK = 0x8001
    ITEMS = {1: "show", 2: "fov", 3: "pos", 4: "exit"}

    def __init__(self, tip, state_fn, post):
        super().__init__(daemon=True)
        self.tip, self.state_fn, self.post = tip, state_fn, post
        self.hwnd, self.ready, self.error, self.added = None, threading.Event(), None, False

    @property
    def ok(self):
        return self.added and self.hwnd is not None

    def set_tip(self, tip):
        self.tip = tip
        if self.hwnd:
            self.nid.szTip = tip[:127]
            self.sh.Shell_NotifyIconW(1, ctypes.byref(self.nid))        # NIM_MODIFY

    def stop(self):
        self.ready.wait(2)
        if self.hwnd:
            self.u.PostMessageW(self.hwnd, 0x0010, 0, 0)                 # WM_CLOSE
        self.join(2)

    def run(self):
        try:
            self._run()
        except Exception as e:           # never leave the UI waiting on a tray that failed to start
            self.error = repr(e)
        finally:
            self.hwnd = None
            self.ready.set()

    def _run(self):
        u = self.u = ctypes.WinDLL("user32", use_last_error=True)
        sh = self.sh = ctypes.WinDLL("shell32")
        k = ctypes.WinDLL("kernel32")
        H, W, L, LR = wt.HWND, wt.WPARAM, wt.LPARAM, ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LR, H, wt.UINT, W, L)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]

        class GUID(ctypes.Structure):
            _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]

        class NID(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("hWnd", H), ("uID", wt.UINT), ("uFlags", wt.UINT),
                        ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", ctypes.c_wchar * 128),
                        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", ctypes.c_wchar * 256),
                        ("uVersion", wt.UINT), ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", wt.DWORD),
                        ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]

        u.DefWindowProcW.argtypes = [H, wt.UINT, W, L]; u.DefWindowProcW.restype = LR
        u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]; u.RegisterClassW.restype = wt.ATOM
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, H, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        u.CreateWindowExW.restype = H
        u.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), H, wt.UINT, wt.UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]; u.DispatchMessageW.restype = LR
        u.PostMessageW.argtypes = [H, wt.UINT, W, L]
        u.DestroyWindow.argtypes = [H]
        u.PostQuitMessage.argtypes = [ctypes.c_int]
        u.CreatePopupMenu.restype = wt.HMENU
        u.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        u.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_void_p]
        u.DestroyMenu.argtypes = [wt.HMENU]
        u.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
        u.SetForegroundWindow.argtypes = [H]
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
        u.LoadImageW.restype = wt.HANDLE
        u.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]; u.RegisterWindowMessageW.restype = wt.UINT
        k.GetModuleHandleW.argtypes = [wt.LPCWSTR]; k.GetModuleHandleW.restype = wt.HMODULE
        sh.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NID)]

        taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")   # explorer restarted: re-add the icon
        nid = self.nid = NID()

        def add():
            self.added = bool(sh.Shell_NotifyIconW(0, ctypes.byref(nid)))   # NIM_ADD

        def menu(hwnd):
            fov_on, pos_on = self.state_fn()
            m = u.CreatePopupMenu()
            u.AppendMenuW(m, 0, 1, "Show window")
            u.AppendMenuW(m, 0x800, 0, None)
            u.AppendMenuW(m, 0x8 if fov_on else 0, 2, "FOV multiplier")
            u.AppendMenuW(m, 0x8 if pos_on else 0, 3, "Viewmodel position")
            u.AppendMenuW(m, 0x800, 0, None)
            u.AppendMenuW(m, 0, 4, "Exit")
            pt = wt.POINT(); u.GetCursorPos(ctypes.byref(pt))
            u.SetForegroundWindow(hwnd)                                  # else the menu never dismisses
            cmd = u.TrackPopupMenu(m, 0x180, pt.x, pt.y, 0, hwnd, None)  # TPM_RETURNCMD | TPM_RIGHTBUTTON
            u.PostMessageW(hwnd, 0, 0, 0)
            u.DestroyMenu(m)
            if cmd in self.ITEMS:
                self.post(self.ITEMS[cmd])

        def proc(hwnd, msg, wp, lp):
            if msg == self.CALLBACK:
                if lp in (0x202, 0x203):                                 # left click / double click
                    self.post("show")
                elif lp == 0x205:                                        # right click
                    menu(hwnd)
                return 0
            if msg == taskbar_created:
                add(); return 0
            if msg == 0x0010:                                            # WM_CLOSE
                u.DestroyWindow(hwnd); return 0
            if msg == 0x0002:                                            # WM_DESTROY
                sh.Shell_NotifyIconW(2, ctypes.byref(nid))               # NIM_DELETE
                u.PostQuitMessage(0); return 0
            return u.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = WNDPROC(proc)                                       # keep a reference alive
        cls = WNDCLASS(); cls.lpfnWndProc = self._proc; cls.hInstance = k.GetModuleHandleW(None)
        cls.lpszClassName = "DirtyBombViewmodelTray"
        u.RegisterClassW(ctypes.byref(cls))
        self.hwnd = u.CreateWindowExW(0, cls.lpszClassName, "tray", 0, 0, 0, 0, 0, -3, None, cls.hInstance, None)  # HWND_MESSAGE
        small = u.GetSystemMetrics(49)                                   # SM_CXSMICON
        nid.cbSize = ctypes.sizeof(NID); nid.hWnd = self.hwnd; nid.uID = 1
        nid.uFlags = 0x7                                                 # NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.CALLBACK
        nid.hIcon = u.LoadImageW(None, ICON, 1, small, small, 0x10)      # IMAGE_ICON, LR_LOADFROMFILE
        nid.szTip = self.tip[:127]
        add()
        if not self.added:
            raise OSError("Shell_NotifyIcon refused the icon")
        self.ready.set()
        msg = wt.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))

# ---------------------------------------------------------------- widgets ---

class HoldButton(tk.Label):
    """Flat button; with repeat=True it auto-repeats while held."""

    def __init__(self, parent, text, command, repeat=False, bg=CARD2, accent=False, **kw):
        super().__init__(parent, text=text, bg=bg, fg=TEXT, font=F["btn"], cursor="hand2",
                         padx=px(11), pady=px(4), **kw)
        self.command, self.repeat, self.base, self.job = command, repeat, bg, None
        self.accent = accent
        self.bind("<Enter>", lambda e: self.config(bg=LINE))
        self.bind("<Leave>", lambda e: (self._stop(), self.config(bg=self.base, fg=TEXT)))
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<ButtonRelease-1>", lambda e: (self._stop(), self.config(bg=LINE, fg=TEXT)))

    def _down(self, _):
        self.config(bg=ACCENT, fg="#111")
        self.command()
        if self.repeat:
            self.job = self.after(380, self._rep)

    def _rep(self):
        self.command()
        self.job = self.after(55, self._rep)

    def _stop(self):
        if self.job:
            self.after_cancel(self.job); self.job = None

class Slider(tk.Canvas):
    PAD = 12

    def __init__(self, parent, lo, hi, step, value, command):
        super().__init__(parent, height=px(28), bg=CARD, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.step, self.value, self.command = lo, hi, step, value, command
        self.hover = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self._mouse)
        self.bind("<B1-Motion>", self._mouse)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<MouseWheel>", lambda e: self._set_user(self.value + (self.step if e.delta > 0 else -self.step)))

    def _hover(self, on):
        self.hover = on; self.draw()

    def _x(self, v):
        pad = px(self.PAD)
        return pad + (v - self.lo) / (self.hi - self.lo) * (self.winfo_width() - 2 * pad)

    def set(self, v):
        self.value = max(self.lo, min(self.hi, v)); self.draw()

    def _set_user(self, v):
        v = round(round((v - self.lo) / self.step) * self.step + self.lo, 2)
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v; self.draw(); self.command(v)

    def _mouse(self, e):
        pad = px(self.PAD)
        t = (e.x - pad) / max(1, self.winfo_width() - 2 * pad)
        self._set_user(self.lo + max(0.0, min(1.0, t)) * (self.hi - self.lo))

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        y, pad, tw = h // 2, px(self.PAD), px(5)
        x = self._x(self.value)
        self.create_line(pad, y, w - pad, y, width=tw, capstyle="round", fill=LINE)
        self.create_line(pad, y, x, y, width=tw, capstyle="round", fill=ACCENT)
        r = px(9 if self.hover else 8)
        g = r + px(5)
        self.create_oval(x - g, y - g, x + g, y + g, fill=blend(CARD, ACCENT, 0.22), outline="")
        self.create_oval(x - r, y - r, x + r, y + r, fill="#ffffff", outline=ACCENT, width=px(2))

class Switch(tk.Canvas):
    def __init__(self, parent, value, command):
        self.w, self.h = px(46), px(24)
        super().__init__(parent, width=self.w, height=self.h, bg=CARD, highlightthickness=0, cursor="hand2")
        self.value, self.command = value, command
        self.t = 1.0 if value else 0.0
        self.bind("<Button-1>", lambda e: (self.set(not self.value), self.command(self.value)))
        self.draw()

    def set(self, v):
        if v != self.value:
            self.value = v; self._anim()

    def _anim(self):
        goal = 1.0 if self.value else 0.0
        self.t += max(-0.25, min(0.25, goal - self.t))
        self.draw()
        if self.t != goal:
            self.after(16, self._anim)

    def draw(self):
        self.delete("all")
        r = self.h // 2
        self.create_line(r, r, self.w - r, r, width=self.h - 2, capstyle="round",
                         fill=blend(LINE, ACCENT, self.t))
        x = r + self.t * (self.w - 2 * r)
        k = r - px(4)
        self.create_oval(x - k, r - k, x + k, r + k, fill="#ffffff", outline="")

class ParamRow(tk.Frame):
    def __init__(self, parent, title, store, key, lo, hi, step, fmt, on_change):
        super().__init__(parent, bg=CARD)
        self.store, self.key, self.lo, self.hi, self.step = store, key, lo, hi, step
        self.fmt, self.on_change = fmt, on_change
        head = tk.Frame(self, bg=CARD); head.pack(fill="x")
        tk.Label(head, text=title, bg=CARD, fg=TEXT, font=F["text"]).pack(side="left")
        self.readout = tk.Label(head, bg=CARD, fg=ACCENT, font=F["mono"]); self.readout.pack(side="right")
        line = tk.Frame(self, bg=CARD); line.pack(fill="x", pady=(px(4), 0))
        HoldButton(line, "−", lambda: self.bump(-1), repeat=True).pack(side="left")
        HoldButton(line, "+", lambda: self.bump(1), repeat=True).pack(side="right")
        self.slider = Slider(line, lo, hi, step, store[key], self.apply)
        self.slider.pack(side="left", fill="x", expand=True, padx=px(6))
        self.sync()

    def bump(self, d):
        self.apply(round(max(self.lo, min(self.hi, self.store[self.key] + d * self.step)), 2))

    def apply(self, v):
        self.store[self.key] = v
        self.slider.set(v)
        self.readout.config(text=self.fmt.format(v))
        self.on_change()

    def sync(self):
        v = self.store[self.key]
        self.slider.set(v)
        self.readout.config(text=self.fmt.format(v))

class Preview(tk.Canvas):
    """Schematic of the current settings: weapon offset on screen plus an FOV wedge."""

    def __init__(self, parent, fov_s, pos_s):
        super().__init__(parent, width=px(270), height=px(190), bg=CARD, highlightthickness=0)
        self.fov_s, self.pos_s = fov_s, pos_s
        self.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        m = px(8)
        self.create_rectangle(m, m, w - m, h - m, outline=LINE, fill=blend(BG, CARD, 0.6))
        cx, cy = w // 2, h // 2
        c = px(8)
        for a, b, c2, d in ((cx - c, cy, cx + c, cy), (cx, cy - c, cx, cy + c)):
            self.create_line(a, b, c2, d, fill=MUTED)
        fs, ps = self.fov_s, self.pos_s
        fov = 52 * (fs["scale"] if fs["enabled"] else 1.0)
        # FOV wedge (top-left)
        ox, oy, rad = px(40), px(78), px(50)
        self.create_arc(ox - rad, oy - rad, ox + rad, oy + rad, start=90 - fov / 2, extent=fov,
                        fill=blend(CARD, ACCENT, 0.2), outline=ACCENT, style="pieslice")
        self.create_text(ox + px(46), oy - px(52), text=f"{fov:.0f}°", fill=ACCENT, font=F["mono"], anchor="w")
        # weapon silhouette, offset by right/down, sized by forward and FOV
        on = ps["enabled"]
        dx = ps["right"] * px(4) if on else 0
        dy = ps["down"] * px(4) if on else 0
        k = px(1) * max(0.4, (1 + (ps["forward"] * 0.03 if on else 0))) / (fov / 52) ** 0.5
        ax, ay = w * 0.70 + dx, h * 0.80 + dy
        def P(*pts):
            return [v for x, y in zip(pts[::2], pts[1::2]) for v in (ax + x * k, ay + y * k)]
        for pts in ((-70, -14, 40, -14, 40, 14, -70, 14),
                    (-130, -6, -70, -6, -70, 4, -130, 4),
                    (-14, 14, 18, 14, 8, 52, -22, 52),
                    (-50, 14, -30, 14, -34, 40, -54, 40)):
            self.create_polygon(P(*pts), fill=CARD2, outline=ACCENT, width=px(2))
        self.create_text(w - m - px(6), m + px(8), text="schematic preview", anchor="e", fill=MUTED, font=F["small"])

# -------------------------------------------------------------------- app ---

STATES = {
    "waiting": ("WAITING FOR DIRTY BOMB", WARN, True),
    "loading": ("ATTACHING…", WARN, True),
    "hooked": ("HOOKED", OK, False),
    "partial": ("PARTIAL HOOK", WARN, False),
    "failed": ("HOOK FAILED · RETRYING", BAD, False),
}

class App:
    def __init__(self, root, selftest=False):
        self.root = root
        self.fov_s = dbmem.load_settings(fovmod.SETTINGS_FILE, fovmod.DEFAULTS)
        self.pos_s = dbmem.load_settings(posmod.SETTINGS_FILE, posmod.DEFAULTS)
        self.events = queue.Queue()
        self.engine = Engine(self.fov_s, self.pos_s, self.events)
        self.state, self.phase, self.save_job = "waiting", 0.0, None
        self.cfg, self.tray = load_config(), None

        root.title("Dirty Bomb Viewmodel Tool")
        root.configure(bg=BG)
        root.geometry(f"{px(1080)}x{px(640)}")
        root.minsize(px(1000), px(600))
        dark_titlebar(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Unmap>", self.on_unmap)
        try:
            root.iconbitmap(ICON)
        except tk.TclError:
            pass
        atexit.register(self.engine.stop)

        self.build()
        self.set_state("waiting")
        self.changed()
        if not selftest and not self.cfg["accepted"]:
            self.consent()
        else:
            self.start_engine()
        self.apply_tray()
        if "--tray" in sys.argv and self.cfg["accepted"]:   # launched by "Start with Windows"
            root.after(1000, lambda: root.withdraw() if self.tray and self.tray.ok else root.iconify())
        self.tick()
        self.poll()

    # ---- layout
    def build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1, uniform="c"); r.grid_columnconfigure(1, weight=1, uniform="c")
        r.grid_columnconfigure(2, weight=0, minsize=px(310)); r.grid_rowconfigure(1, weight=1)
        pad = px(14)

        head = tk.Frame(r, bg=BG); head.grid(row=0, column=0, columnspan=3, sticky="ew", padx=pad, pady=(pad, px(8)))
        tk.Label(head, text="VIEWMODEL", bg=BG, fg=ACCENT, font=F["title"]).pack(side="left")
        tk.Label(head, text=" TOOL", bg=BG, fg=TEXT, font=F["title"]).pack(side="left")
        tk.Label(head, text="   Dirty Bomb · live memory hook · offline only", bg=BG, fg=MUTED,
                 font=F["small"]).pack(side="left", pady=(px(8), 0))
        self.pill = tk.Canvas(head, width=px(250), height=px(30), bg=BG, highlightthickness=0)
        self.pill.pack(side="right")
        HoldButton(head, "⚙  Settings", self.settings_panel, bg=BG).pack(side="right", padx=(0, px(10)))

        self.fov_card = self.card(0, "FOV MULTIPLIER", "Scales the weapon FOV every frame.",
                                  self.fov_s, self.on_fov_toggle)
        self.fov_row = ParamRow(self.fov_card, "Scale", self.fov_s, "scale", fovmod.MIN_SCALE, fovmod.MAX_SCALE,
                                fovmod.STEP, "×{:.2f}", self.on_fov)
        self.fov_row.pack(fill="x", pady=(px(14), 0))
        self.fov_note = tk.Label(self.fov_card, bg=CARD, fg=MUTED, font=F["small"], anchor="w")
        self.fov_note.pack(fill="x", pady=(px(6), px(10)))
        pr = tk.Frame(self.fov_card, bg=CARD); pr.pack(fill="x")
        tk.Label(pr, text="Presets", bg=CARD, fg=MUTED, font=F["small"]).pack(side="left", padx=(0, px(8)))
        for v, name in ((1.0, "Stock"), (1.25, "1.25"), (1.5, "1.5"), (1.75, "1.75"), (2.0, "2.0")):
            HoldButton(pr, name, lambda v=v: self.fov_row.apply(v)).pack(side="left", padx=(0, px(4)))
        self.keys(self.fov_card, [("F7", "toggle"), ("F8", "smaller"), ("F9", "bigger")])

        self.pos_card = self.card(1, "VIEWMODEL POSITION", "Moves the held weapon on screen.",
                                  self.pos_s, self.on_pos_toggle)
        self.pos_rows = []
        for title, key, fmt in (("Horizontal  (right +)", "right", "{:+.2f}"),
                                ("Vertical  (down +)", "down", "{:+.2f}"),
                                ("Depth  (further +)", "forward", "{:+.2f}")):
            row = ParamRow(self.pos_card, title, self.pos_s, key, -posmod.LIMIT, posmod.LIMIT,
                           posmod.STEP, fmt, self.on_pos)
            row.pack(fill="x", pady=(px(12), 0)); self.pos_rows.append(row)
        pr = tk.Frame(self.pos_card, bg=CARD); pr.pack(fill="x", pady=(px(14), 0))
        HoldButton(pr, "Reset offset", self.reset_pos).pack(side="left")
        self.keys(self.pos_card, [("Num5", "toggle"), ("4/6", "left·right"), ("8/2", "up·down"),
                                  ("7/9", "depth"), ("Num0", "reset")])

        side = tk.Frame(r, bg=BG); side.grid(row=1, column=2, sticky="nsew", padx=(0, pad), pady=(0, pad))
        side.grid_rowconfigure(1, weight=1); side.grid_columnconfigure(0, weight=1)
        pv = self.frame(side); pv.grid(row=0, column=0, sticky="ew")
        self.preview = Preview(pv, self.fov_s, self.pos_s); self.preview.pack(fill="x", padx=px(10), pady=px(10))
        lg = self.frame(side); lg.grid(row=1, column=0, sticky="nsew", pady=(px(10), 0))
        tk.Label(lg, text="ACTIVITY", bg=CARD, fg=MUTED, font=F["small"]).pack(anchor="w", padx=px(12), pady=(px(10), 0))
        self.log = tk.Text(lg, bg=CARD, fg=TEXT, font=F["small"], relief="flat", height=6, wrap="word",
                           state="disabled", highlightthickness=0, padx=px(12), pady=px(6), width=10)
        self.log.pack(fill="both", expand=True)

        foot = tk.Frame(r, bg=BG); foot.grid(row=2, column=0, columnspan=3, sticky="ew", padx=pad, pady=(0, pad))
        tk.Label(foot, text="⚠ Use with EAC off / offline only. Not affiliated with Splash Damage or Warchest.",
                 bg=BG, fg=MUTED, font=F["small"]).pack(side="left")
        HoldButton(foot, "Reset all", self.reset_all, bg=BG).pack(side="right")
        pin = Switch(foot, False, lambda v: self.root.attributes("-topmost", v)); pin.config(bg=BG)
        pin.pack(side="right", padx=(px(6), px(14)))
        tk.Label(foot, text="Keep on top", bg=BG, fg=MUTED, font=F["small"]).pack(side="right")

    def frame(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)

    def card(self, col, title, sub, store, on_toggle):
        pad = px(14)
        f = self.frame(self.root); f.grid(row=1, column=col, sticky="nsew",
                                          padx=(pad, px(7) if col == 0 else px(7)), pady=(0, pad))
        inner = tk.Frame(f, bg=CARD); inner.pack(fill="both", expand=True, padx=px(18), pady=px(16))
        top = tk.Frame(inner, bg=CARD); top.pack(fill="x")
        tk.Label(top, text=title, bg=CARD, fg=TEXT, font=F["h2"]).pack(side="left")
        sw = Switch(top, store["enabled"], on_toggle); sw.pack(side="right")
        tk.Label(inner, text=sub, bg=CARD, fg=MUTED, font=F["small"], anchor="w").pack(fill="x")
        inner.switch = sw
        return inner

    def keys(self, parent, items):
        f = tk.Frame(parent, bg=CARD); f.pack(side="bottom", fill="x", pady=(px(14), 0))
        tk.Label(f, text="In-game hotkeys", bg=CARD, fg=MUTED, font=F["small"]).pack(anchor="w", pady=(0, px(4)))
        for i in range(0, len(items), 3):   # three chips per line so the card never overflows
            row = tk.Frame(f, bg=CARD); row.pack(anchor="w", pady=(0, px(3)))
            for k, name in items[i:i + 3]:
                tk.Label(row, text=k, bg=CARD2, fg=TEXT, font=F["mono"], padx=px(6), pady=px(1)).pack(side="left")
                tk.Label(row, text=name, bg=CARD, fg=MUTED, font=F["small"]).pack(side="left", padx=(px(4), px(10)))

    def start_engine(self):
        if "--no-hook" not in sys.argv:   # lets the UI be previewed without touching a running game
            self.engine.start()

    # ---- first-run consent page
    def consent(self):
        ov = tk.Frame(self.root, bg=BG); ov.place(relx=0, rely=0, relwidth=1, relheight=1)
        box = self.frame(ov); box.place(relx=0.5, rely=0.5, anchor="center")
        inner = tk.Frame(box, bg=CARD); inner.pack(padx=px(36), pady=px(30))
        tk.Label(inner, text="Before you start", bg=CARD, fg=ACCENT, font=F["title"]).pack(anchor="w")
        msg = ("This tool edits Dirty Bomb's memory while the game runs.\n\n"
               "•  Dirty Bomb uses EasyAntiCheat. Only use this offline / with EAC disabled.\n"
               "•  Using it on protected servers can get you kicked or banned.\n"
               "•  It can crash the game. It is provided as is, with no warranty.\n"
               "•  Everything is undone when you close this window.")
        tk.Label(inner, text=msg, bg=CARD, fg=TEXT, font=F["text"], justify="left").pack(anchor="w", pady=px(14))
        var = tk.BooleanVar()
        btn = HoldButton(inner, "Continue", lambda: go() if var.get() else None)
        btn.config(fg=MUTED)
        def toggled():
            btn.config(fg=TEXT if var.get() else MUTED)
        tk.Checkbutton(inner, text="I understand and will only use this offline / with EAC off.", variable=var,
                       command=toggled, bg=CARD, fg=TEXT, selectcolor=CARD2, activebackground=CARD,
                       activeforeground=TEXT, font=F["text"], highlightthickness=0).pack(anchor="w")
        btn.pack(anchor="e", pady=(px(16), 0))
        def go():
            self.cfg["accepted"] = True
            save_config(self.cfg)
            ov.destroy()
            self.start_engine()

    # ---- settings page
    def settings_panel(self):
        ov = tk.Frame(self.root, bg=BG); ov.place(relx=0, rely=0, relwidth=1, relheight=1)
        box = self.frame(ov); box.place(relx=0.5, rely=0.5, anchor="center")
        inner = tk.Frame(box, bg=CARD); inner.pack(padx=px(36), pady=px(30))
        tk.Label(inner, text="Settings", bg=CARD, fg=ACCENT, font=F["title"]).pack(anchor="w", pady=(0, px(8)))

        def option(title, sub, value, command):
            row = tk.Frame(inner, bg=CARD); row.pack(fill="x", pady=px(9))
            col = tk.Frame(row, bg=CARD); col.pack(side="left", fill="x", expand=True, padx=(0, px(30)))
            tk.Label(col, text=title, bg=CARD, fg=TEXT, font=F["h2"]).pack(anchor="w")
            tk.Label(col, text=sub, bg=CARD, fg=MUTED, font=F["small"], justify="left").pack(anchor="w")
            Switch(row, value, command).pack(side="right")

        option("Start with Windows", "Launch automatically when you sign in, minimised\nto the tray, ready for Dirty Bomb.",
               startup_enabled(), self.opt_startup)
        option("Minimise to system tray", "Minimising hides the window to the notification area.\n"
               "The tool keeps running; click the tray icon to reopen it.", self.cfg["tray"], self.opt_tray)
        tk.Label(inner, text=f"Settings folder: {DATA_DIR}", bg=CARD, fg=MUTED, font=F["small"]).pack(anchor="w", pady=(px(10), 0))
        HoldButton(inner, "Done", ov.destroy).pack(anchor="e", pady=(px(14), 0))

    def opt_startup(self, on):
        try:
            set_startup(on)
        except OSError as e:
            messagebox.showerror("Start with Windows", f"Could not update the startup entry:\n{e}")

    def opt_tray(self, on):
        self.cfg["tray"] = on
        save_config(self.cfg)
        self.apply_tray()

    # ---- tray
    def apply_tray(self):
        if self.cfg["tray"] and not self.tray:
            self.tray = Tray(self.tip(), lambda: (self.fov_s["enabled"], self.pos_s["enabled"]),
                             lambda name: self.events.put(("tray", name)))
            self.tray.start()
            self.root.after(1500, self.check_tray)
        elif not self.cfg["tray"] and self.tray:
            self.tray.stop(); self.tray = None
            self.show_window()

    def check_tray(self):
        if self.tray and not self.tray.ok:
            self.write(f"System tray unavailable ({self.tray.error or 'unknown error'}); minimising uses the taskbar.")

    def tip(self):
        return "Viewmodel Tool - " + STATES[self.state][0].title()

    def on_unmap(self, e):
        if e.widget is self.root and self.cfg["tray"] and self.tray and self.tray.ok and self.root.state() == "iconic":
            self.root.after_idle(self.root.withdraw)

    def show_window(self):
        self.root.deiconify(); self.root.state("normal"); self.root.lift(); self.root.focus_force()

    # ---- callbacks (UI thread)
    def on_fov(self):
        self.engine.touch_fov(); self.changed()

    def on_pos(self):
        self.engine.touch_pos(); self.changed()

    def on_fov_toggle(self, v):
        self.fov_s["enabled"] = v; self.on_fov()

    def on_pos_toggle(self, v):
        self.pos_s["enabled"] = v; self.on_pos()

    def reset_pos(self):
        for row in self.pos_rows:
            row.apply(0.0)

    def reset_all(self):
        self.reset_pos()
        self.fov_row.apply(fovmod.DEFAULTS["scale"])
        self.fov_card.switch.set(True); self.on_fov_toggle(True)
        self.pos_card.switch.set(True); self.on_pos_toggle(True)

    def changed(self):
        self.fov_note.config(text=f"Default rifle FOV 52°  →  {52 * self.fov_s['scale']:.0f}°"
                                  + ("" if self.fov_s["enabled"] else "   (off)"))
        self.preview.draw()
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(300, self.save)

    def save(self):
        self.save_job = None
        dbmem.save_settings(fovmod.SETTINGS_FILE, self.fov_s)
        dbmem.save_settings(posmod.SETTINGS_FILE, self.pos_s)

    def sync(self):
        self.fov_row.sync()
        for row in self.pos_rows:
            row.sync()
        self.fov_card.switch.set(self.fov_s["enabled"])
        self.pos_card.switch.set(self.pos_s["enabled"])
        self.changed()

    # ---- engine events, status pill
    def poll(self):
        try:
            while True:
                kind, *args = self.events.get_nowait()
                if kind == "state":
                    if args[0] != self.state:
                        self.set_state(args[0])
                        if args[0] == "waiting":
                            self.write("Waiting for the game to start…")
                elif kind == "hooks":
                    fok, ferr, pok, perr = args
                    self.set_state("hooked" if fok and pok else "partial" if fok or pok else "failed")
                    self.write("FOV hook: " + ("attached" if fok else f"failed ({ferr})"))
                    self.write("Position hook: " + ("attached" if pok else f"failed ({perr})"))
                elif kind == "sync":
                    self.sync()
                elif kind == "tray":
                    name = args[0]
                    if name == "show":
                        self.show_window()
                    elif name == "fov":
                        v = not self.fov_s["enabled"]; self.fov_card.switch.set(v); self.on_fov_toggle(v)
                    elif name == "pos":
                        v = not self.pos_s["enabled"]; self.pos_card.switch.set(v); self.on_pos_toggle(v)
                    elif name == "exit":
                        self.close(); return
                elif kind == "log":
                    self.write(args[0])
        except queue.Empty:
            pass
        self.root.after(40, self.poll)

    def set_state(self, name):
        self.state = name
        if self.tray:
            self.tray.set_tip(self.tip())

    def tick(self):
        text, color, pulse = STATES[self.state]
        self.phase += 0.12
        k = (0.55 + 0.45 * math.sin(self.phase)) if pulse else 1.0
        c = self.pill; c.delete("all")
        w, h = int(c["width"]), int(c["height"])
        c.create_line(h // 2, h // 2, w - h // 2, h // 2, width=h - 2, capstyle="round", fill=CARD, )
        c.create_oval(px(10), h // 2 - px(5), px(20), h // 2 + px(5), fill=blend(CARD, color, k), outline="")
        c.create_text(px(30), h // 2, text=text, anchor="w", fill=color, font=F["small"])
        self.root.after(50, self.tick)

    def write(self, text):
        self.log.config(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + text + "\n")
        self.log.see("end"); self.log.config(state="disabled")

    def close(self):
        if self.save_job:
            self.save()
        self.engine.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

def claim_instance():
    """Same named mutexes as the console tools, so the GUI and the .bat tools can't fight over the hook."""
    held = []
    for name in ("FOV", "Position"):
        held.append(dbmem.k32.CreateMutexW(None, False, f"Local\\DirtyBombViewmodel_{name}"))
        if ctypes.get_last_error() == 183:
            return None
    return held

def main():
    global SCALE
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    mutexes = claim_instance()
    if mutexes is None:
        messagebox.showerror("Already running",
                             "Another Viewmodel tool (or this GUI) is already running.\nClose it first.")
        return
    root = tk.Tk()
    SCALE = root.winfo_fpixels("1i") / 96
    ui = "Segoe UI"
    F.update(title=tkfont.Font(family=ui, size=17, weight="bold"), h2=tkfont.Font(family=ui, size=11, weight="bold"),
             text=tkfont.Font(family=ui, size=10), small=tkfont.Font(family=ui, size=9),
             btn=tkfont.Font(family=ui, size=10, weight="bold"), mono=tkfont.Font(family="Consolas", size=10, weight="bold"))
    selftest = "--selftest" in sys.argv
    app = App(root, selftest)
    root.report_callback_exception = lambda *a: messagebox.showerror("Error", repr(a[1]))
    if selftest:
        def poke():
            app.fov_row.bump(1); app.pos_rows[0].bump(1); app.reset_all(); app.sync()
            print("selftest ok"); app.close()
        root.after(1500, poke)
    root.mainloop()
    del mutexes

if __name__ == "__main__":
    main()
