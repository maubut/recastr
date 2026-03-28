@echo off
echo ============================================
echo   AUTOZOOM - Editeur de zooms
echo ============================================
echo.

echo Glisse ta VIDEO ici et appuie Enter:
set /p VIDEO="> "

echo.
echo Glisse ton CURSOR LOG (.json) ici et appuie Enter:
set /p LOG="> "

echo.
echo Lancement...
echo.

python "%~dp0auto_zoom.py" %VIDEO% %LOG% --edit

echo.
echo ---- Script termine (code: %errorlevel%) ----
echo.
pause
