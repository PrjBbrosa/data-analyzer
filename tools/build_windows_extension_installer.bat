@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
rem Default config: configs\extension-release\local\repository.json
rem Output: dist\TraceLabExtensionManager\installer.exe

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows_extension_installer.ps1" %*
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%BUILD_EXIT_CODE%"=="0" (echo Installer build succeeded.) else (echo Installer build failed. Exit code: %BUILD_EXIT_CODE%)
if "%~1"=="" pause
exit /b %BUILD_EXIT_CODE%
