@echo off
setlocal

set "APPNAME=MF4DataAnalyzer"
if not "%~1"=="" set "APPNAME=%~1"

set "REPO_ROOT=%~dp0.."
set "EXE=%REPO_ROOT%\dist\%APPNAME%\%APPNAME%.exe"

if not exist "%EXE%" (
    echo Built exe not found:
    echo   %EXE%
    echo.
    echo Build it first, for example:
    echo   tools\build_windows_folder.bat -Console
    pause
    exit /b 1
)

echo Running:
echo   %EXE%
echo.
"%EXE%"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Exit code: %EXITCODE%
pause
exit /b %EXITCODE%
