@echo off
rem Builds a single-file "Dirty Bomb Viewmodel Tool.exe" into GUI\dist using PyInstaller
rem (installed into a throwaway virtual environment, nothing global is touched).
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.8+ not found. Install it from python.org first. & pause & exit /b 1)
if not exist .buildvenv python -m venv .buildvenv || goto :fail
.buildvenv\Scripts\python -m pip install --quiet --upgrade pyinstaller || goto :fail
python make_icon.py >nul
.buildvenv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "Dirty Bomb Viewmodel Tool" --icon "%~dp0assets\icon.ico" --add-data "%~dp0assets\icon.ico;assets" ^
  --paths .. --distpath dist --workpath build --specpath build viewmodel_gui.py || goto :fail
echo.
echo Done: %~dp0dist\Dirty Bomb Viewmodel Tool.exe
exit /b 0
:fail
echo Build failed.
exit /b 1
