@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows_folder_lite.ps1" %*
exit /b %ERRORLEVEL%
