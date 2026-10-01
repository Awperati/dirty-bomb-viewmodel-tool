@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul || (echo Python 3.8+ not found. Install it from python.org, then run this again. & pause & exit /b 1)
start "" pythonw viewmodel_gui.py
