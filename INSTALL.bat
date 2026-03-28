@echo off
echo ============================================
echo   AUTOZOOM v4 - Installation
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python pas installe!
    echo.
    echo 1. Va sur https://www.python.org/downloads/
    echo 2. COCHE "Add Python to PATH" pendant l'install!
    echo 3. Relance ce script apres
    pause
    exit /b 1
)

echo Python OK!
python --version
echo.

echo [1/5] Installation de numpy...
pip install numpy
echo.

echo [2/5] Installation de opencv...
pip install opencv-python
echo.

echo [3/5] Installation de obsws-python (sync OBS)...
pip install obsws-python
echo.

echo [4/5] Installation de Pillow (captions haute qualite)...
pip install Pillow
echo.

echo [5/5] Installation de openai-whisper (captions auto)...
echo NOTE: Whisper est optionnel. Si l'install echoue, les captions ne seront
echo       pas disponibles mais le reste fonctionne normalement.
pip install openai-whisper
echo.

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo NOTE: FFmpeg pas encore installe.
    echo   winget install FFmpeg
    echo   OU telecharge: https://ffmpeg.org/download.html
    echo   FFmpeg est REQUIS pour le rendu video ET pour Whisper.
    echo.
) else (
    echo FFmpeg OK!
    echo.
)

echo ============================================
echo   Installation terminee!
echo.
echo   IMPORTANT - Setup OBS WebSocket:
echo   1. Ouvre OBS
echo   2. Tools ^> WebSocket Server Settings
echo   3. Coche "Enable WebSocket Server"
echo   4. Note le port (default: 4455)
echo.
echo   Workflow:
echo   1. Ouvre OBS (configure ta scene)
echo   2. Lance START_LOGGING.bat (choisis mode OBS)
echo   3. Fais ta demo normalement
echo   4. Ctrl+C pour arreter
echo   5. Lance RENDER_ZOOM.bat (ajoute --captions pour les sous-titres!)
echo ============================================
echo.
pause
