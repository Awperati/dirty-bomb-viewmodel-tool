# Dirty Bomb Viewmodel Tool

Two small Python tools that change how the weapon viewmodel looks in **Dirty Bomb** (Unreal Engine 3), without touching any game files. They patch the running game's memory and undo everything when you close them.

- **`viewmodel_fov.py`** hooks the per-frame copy of the equipped weapon's FOV and multiplies it.
- **`viewmodel_position.py`** shifts the weapon's `m_PlayerViewOffset` (forward / right / up).

They can run side by side (`Run Both.bat`). Both locate their hook site by byte-pattern scan, so they don't depend on fixed addresses.

## Offline use only

Dirty Bomb ships with EasyAntiCheat. **Use this tool only offline / with EAC disabled** (for example a bot match or private session launched without EAC). Patching game memory while EAC is running will likely get you kicked or banned. You are responsible for how you use it.

## Requirements

- Windows (64-bit Dirty Bomb, `shootergame-win32-shipping.exe`)
- Python 3.8+ (standard library only, no pip installs)

## GUI edition (optional)

Prefer sliders and buttons? The [`GUI`](GUI) folder has a one-window version with live adjustment. Run `GUI/Run GUI.bat`, or build a single exe with `GUI/build_exe.bat`. It can sit in the system tray and start with Windows. See [GUI/README.md](GUI/README.md).

## Running

Start the game first or afterwards (the tools wait for it), then double-click:

- `Run Viewmodel FOV.bat`
- `Run Viewmodel Position.bat`
- `Run Both.bat`

or run `python viewmodel_fov.py` / `python viewmodel_position.py` from this folder. Close the window or press Ctrl+C to unhook and restore the original code.

## Hotkeys (work while the game is focused)

| Tool | Key | Action |
|---|---|---|
| FOV | F7 | toggle on/off |
| FOV | F8 / F9 | scale down / up (x0.5 to x3.0, step 0.05) |
| Position | Num5 | toggle on/off |
| Position | Num4 / Num6 | move left / right |
| Position | Num8 / Num2 | move up / down |
| Position | Num7 / Num9 | move closer / further |
| Position | Num0 | reset offset |

Position needs Num Lock on. Your settings are saved next to the scripts in `fov_settings.json` and `position_settings.json`, created on first change. They are git-ignored.

## How it works

`dbmem.py` holds the shared helpers: process lookup, pattern scan, a code cave allocated near the game module, and a `jmp` hook that is removed on exit. If a previous run was killed without unhooking, the next run cleans up the stale hook. If the game is updated and the pattern no longer matches exactly once, the tool refuses to hook.

## Disclaimer

This tool edits another program's memory. It is provided as is, with no warranty; it may crash the game. It is not affiliated with, endorsed by, or connected to Splash Damage or Warchest. "Dirty Bomb" is their trademark. No game assets, data or binaries are included in this repository.
