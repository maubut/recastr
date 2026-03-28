@echo off
setlocal enabledelayedexpansion
echo ============================================
echo   AUTOZOOM - Render final
echo ============================================
echo.

:: Reset variables
set "VIDEO="
set "LOG="
set "EDITED="
set "BGCHOICE="
set "BGARG="
set "CAPARG="
set "CAPCHOICE="

echo Glisse ta VIDEO ici et appuie Enter:
set /p "VIDEO=> "
if not defined VIDEO (
    echo ERREUR: Video requise.
    goto END
)
:: Strip surrounding quotes from drag-and-drop
set VIDEO=!VIDEO:"=!

echo.
echo Glisse ton CURSOR LOG (.json) ici et appuie Enter:
set /p "LOG=> "
if not defined LOG (
    echo ERREUR: Cursor log requis.
    goto END
)
set LOG=!LOG:"=!

echo.
echo As-tu un JSON edite (export de l'editeur)?
echo   Glisse-le ici, ou appuie Enter pour skip:
set /p "EDITED=> "

echo.
echo Veux-tu un background? (le JSON edite peut deja en contenir un)
echo   1 = Carbon (sombre, texture subtile)
echo   2 = Gradient (bleu-violet diagonal)
echo   3 = Mesh (grille sombre)
echo   Enter = Aucun / utiliser celui du JSON
echo.
set /p "BGCHOICE=> "

if "!BGCHOICE!"=="1" set "BGARG=--background carbon"
if "!BGCHOICE!"=="2" set "BGARG=--background gradient"
if "!BGCHOICE!"=="3" set "BGARG=--background mesh"

echo.
echo Veux-tu des captions (sous-titres auto Whisper)?
echo   1 = Oui, style TikTok (gros texte centre, mot par mot)
echo   2 = Oui, style classique (bas de l'ecran)
echo   Enter = Non / utiliser celles du JSON
echo.
set /p "CAPCHOICE=> "

if "!CAPCHOICE!"=="1" set "CAPARG=--captions --caption-style tiktok"
if "!CAPCHOICE!"=="2" set "CAPARG=--captions --caption-style classic"

echo.

:: Check if edited JSON was provided
if not defined EDITED goto AUTO_RENDER
:: Strip quotes from edited path too
set EDITED=!EDITED:"=!

:EDITED_RENDER
echo Render avec zooms edites...
echo   Video:    "!VIDEO!"
echo   Log:      "!LOG!"
echo   Edited:   "!EDITED!"
if defined CAPARG echo   Captions: oui
echo.
python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" --use-edited "!EDITED!" !BGARG! !CAPARG!
goto DONE

:AUTO_RENDER
echo Render avec zooms auto-detectes...
echo   Video:    "!VIDEO!"
echo   Log:      "!LOG!"
if defined CAPARG echo   Captions: oui
echo.
python "%~dp0auto_zoom.py" "!VIDEO!" "!LOG!" !BGARG! !CAPARG!
goto DONE

:DONE
echo.
echo ---- Termine (code: %errorlevel%) ----

:END
echo.
pause
endlocal
