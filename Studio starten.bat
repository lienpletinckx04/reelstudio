@echo off
setlocal
REM ══════════════════════════════════════════════════════════════════
REM  Studio starten.bat — dubbelklik dit bestand om de studio te openen.
REM  Windows-versie van "Studio starten.command".
REM ══════════════════════════════════════════════════════════════════
cd /d "%~dp0"
echo Reelstudio studio starten ...
echo (dit venster mag je laten staan; sluiten stopt de studio)
echo.
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python reelstudio.py studio
) else (
    python3 reelstudio.py studio
)
echo.
pause
