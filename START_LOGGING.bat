@echo off
echo ============================================
echo   AUTOZOOM v4 - Cursor Logger
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python pas installe!
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Choisis ton mode:
echo.
echo   1. Mode OBS (recommande, tente de cacher le curseur OBS)
echo   2. Mode OBS (garde le curseur visible)
echo   3. Mode standalone (clic sur fenetre)
echo   4. Mode plein ecran
echo.
set /p MODE="Ton choix (1, 2, 3 ou 4): "

if "%MODE%"=="1" goto OBS_HIDE
if "%MODE%"=="2" goto OBS_KEEP
if "%MODE%"=="3" goto STANDALONE
if "%MODE%"=="4" goto FULLSCREEN
goto STANDALONE

:OBS_HIDE
echo.
echo Connexion a OBS...
echo Assure-toi que OBS est ouvert avec WebSocket active!
echo Le script tentera de desactiver le curseur dans OBS.
echo NOTE: Ca ne marche pas sur toutes les configs (ex: Display Capture DXGI).
echo Si le curseur est encore visible, desactive-le manuellement dans OBS:
echo   Clic droit sur ta source ^> Proprietes ^> decocher 'Capture Cursor'
echo.
python "%~dp0cursor_logger.py" --obs
goto END

:OBS_KEEP
echo.
echo Connexion a OBS (curseur natif garde visible)...
echo.
python "%~dp0cursor_logger.py" --obs --keep-cursor
goto END

:STANDALONE
echo.
echo Mode standalone.
echo Tu vas devoir cliquer sur la fenetre que OBS capture.
echo.
python "%~dp0cursor_logger.py"
goto END

:FULLSCREEN
echo.
python "%~dp0cursor_logger.py" --fullscreen
goto END

:END
echo.
echo ---- Termine ----
echo.
pause
