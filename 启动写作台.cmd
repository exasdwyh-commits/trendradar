@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\launch.py" %*
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 "scripts\launch.py" %*
  ) else (
    python "scripts\launch.py" %*
  )
)
set "launch_exit=%errorlevel%"
if errorlevel 1 (
  echo.
  echo Startup failed. Read the error above, then press any key to close.
  pause >nul
)
exit /b %launch_exit%
