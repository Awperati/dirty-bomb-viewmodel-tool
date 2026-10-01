# Viewmodel Tool - GUI edition (optional)

A single window for both tools: toggles, +/- buttons (hold to repeat), live sliders, FOV presets, a schematic preview and an activity log. Changes apply in-game instantly. The in-game hotkeys (F7/F8/F9 and the numpad) still work while the window is open, and the sliders follow them.

## Run

Double-click **`Run GUI.bat`** (or `pythonw GUI\viewmodel_gui.py`). It needs Windows and Python 3.8+; there is nothing to install.

The GUI reuses `dbmem.py`, `viewmodel_fov.py` and `viewmodel_position.py` from the parent folder, so download or clone the whole repository and keep the `GUI` folder where it is. It shares the settings files and the single-instance lock with the console tools, so don't run both at once.

On first launch you accept an offline-only notice, stored in `GUI/gui_config.json`. Closing the window unhooks the game and restores the original weapon offset.

**Offline / EAC off only.** See the main README for the risks.
