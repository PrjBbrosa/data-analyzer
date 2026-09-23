@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows_folder_lite_modular.ps1" %*
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%BUILD_EXIT_CODE%"=="0" (echo Modular build succeeded.) else (echo Modular build failed. Exit code: %BUILD_EXIT_CODE%)
if "%~1"=="" pause
exit /b %BUILD_EXIT_CODE%
