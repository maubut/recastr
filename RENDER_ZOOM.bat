@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   AUTOZOOM v4 - Render
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python manquant!
    echo https://www.python.org/downloads/
    goto :done
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: FFmpeg manquant!
    echo   winget install FFmpeg
    goto :done
)

python -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo Installation numpy...
    pip install numpy
    echo.
)

echo Glisse ta VIDEO ici:
set /p VIDEO="> "
echo.
echo Glisse ton CURSOR LOG (.json) ici:
set /p LOG="> "

:: Enlever les guillemets
set "VIDEO=!VIDEO:"=!"
set "LOG=!LOG:"=!"

echo.
echo ============================================
echo   Que veux-tu faire?
echo ============================================
echo.
echo   1. EDITEUR  - ouvre l'editeur visuel dans ton browser
echo   2. DEBUG    - video avec curseur vert dessine
echo   3. RENDER   - generer la video finale
echo   4. RENDER avec JSON edite (export de l'editeur)
echo.
set /p CHOIX="Ton choix (1, 2, 3 ou 4): "

echo.

if "!CHOIX!"=="1" (
    echo Lancement de l'editeur...
    echo.
    python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" --edit
    if errorlevel 1 (
        echo.
        echo --- ERREUR: le script a plante ---
        echo Verifie que ta video et ton JSON sont valides.
    )
) else if "!CHOIX!"=="2" (
    python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" --debug
) else if "!CHOIX!"=="4" (
    echo Glisse le JSON edite (zoom_events_edited.json) ici:
    set /p EDITED="> "
    set "EDITED=!EDITED:"=!"
    python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" --use-edited "!EDITED!"
) else (
    set /p "OFFSET=Offset en secondes (Enter pour 0): "
    if defined OFFSET (
        python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" --offset !OFFSET!
    ) else (
        python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!"
    )
)

:done
echo.
echo Appuie sur une touche pour fermer...
pause >nul
