@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%~1"=="" (
    echo Usage: build_windows_extension_installer.bat -RepositoryConfig path\to\repository.json
    echo Local placeholder: -RepositoryConfig configs\extension-release\local\repository.json
    echo Output: dist\TraceLabExtensionManager\installer.exe
    exit /b 2
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows_extension_installer.ps1" %*
exit /b %ERRORLEVEL%
