@echo off
cd /d "%~dp0"
start "Dirty Bomb Viewmodel FOV" cmd /c "python viewmodel_fov.py & pause"
start "Dirty Bomb Viewmodel Position" cmd /c "python viewmodel_position.py & pause"
