@echo off
title Aura widget setup
echo Installing what the widgets need...
py -m pip install --upgrade -r "%~dp0requirements.txt"
if errorlevel 1 (
  python -m pip install --upgrade -r "%~dp0requirements.txt"
)
echo.
echo Done. Starting the widget...
start "" pyw "%~dp0aura_widget.pyw" 2>nul || start "" pythonw "%~dp0aura_widget.pyw"
timeout /t 3 >nul
