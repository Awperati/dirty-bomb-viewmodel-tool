# Viewmodel Tool - GUI edition (optional)

A single window for both tools: toggles, +/- buttons (hold to repeat), live sliders, FOV presets, a schematic preview and an activity log. Changes apply in-game instantly. The in-game hotkeys (F7/F8/F9 and the numpad) still work while the window is open, and the sliders follow them.

Open it alongside Dirty Bomb (before or after the game starts; it waits for the game and attaches automatically) and minimise it to the system tray to leave it running in the background.

## Settings (⚙ button)

- **Start with Windows:** adds a per-user startup entry (no admin needed) that launches the tool minimised to the tray.
- **Minimise to system tray:** minimising hides the window to the notification area. Left-click the tray icon to reopen; right-click for Show window / FOV on-off / Position on-off / Exit.

## Run

**Single exe:** build it once with `build_exe.bat` (needs Python 3.8+; PyInstaller is installed into a throwaway `.buildvenv`) and use `dist\Dirty Bomb Viewmodel Tool.exe`. It is fully standalone and keeps its settings in `%APPDATA%\DirtyBombViewmodelTool`. Pre-built exes may be attached to GitHub releases.

**From source:** double-click `Run GUI.bat` (or `pythonw GUI\viewmodel_gui.py`). Nothing to install, but it reuses `dbmem.py`, `viewmodel_fov.py` and `viewmodel_position.py` from the parent folder, so keep the `GUI` folder inside the repository.

On first launch you accept an offline-only notice. Closing the window (or choosing Exit in the tray menu) unhooks the game and restores the original weapon offset.

The GUI shares its settings files and single-instance lock with the console tools, so don't run both at once.

## Notes

- Unsigned PyInstaller exes that write to another process's memory are commonly flagged by antivirus; you can build it yourself from the source here.
- **Offline / EAC off only.** See the main README for the risks.
