@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows_folder_lite.ps1" %*
set "BUILD_EXITCODE=%ERRORLEVEL%"
if not "%BUILD_EXITCODE%"=="0" (
    echo.
    echo Lite build failed. Exit code: %BUILD_EXITCODE%
    echo See the full build log path printed above.
    pause
)
exit /b %BUILD_EXITCODE%
