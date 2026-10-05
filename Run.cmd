@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run.ps1"
set result=%ERRORLEVEL%
echo.
if "%result%"=="0" echo Collection completed successfully. Open report.html to view the report.
if "%result%"=="1" echo Collection failed. Review the newest file in logs for details.
if "%result%"=="2" echo Report created with source coverage warnings. Open report.html and review Source Health.
if "%result%"=="3" echo Collection did not start because another run or lock is present.
if not "%result%"=="0" if not "%result%"=="1" if not "%result%"=="2" if not "%result%"=="3" echo Finished with unexpected code %result%. Review the newest file in logs.
pause
exit /b %result%
