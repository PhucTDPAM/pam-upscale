@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Chua cai dat - dang chay cai_dat.bat ...
    call "%~dp0cai_dat.bat"
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
