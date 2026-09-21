@echo off
title Aura widget setup
echo Installing what the widget needs...
py -m pip install --upgrade PyQt6 Pillow winrt-runtime winrt-Windows.Media.Control winrt-Windows.Storage.Streams winrt-Windows.Foundation winrt-Windows.Foundation.Collections
if errorlevel 1 (
  python -m pip install --upgrade PyQt6 Pillow winrt-runtime winrt-Windows.Media.Control winrt-Windows.Storage.Streams winrt-Windows.Foundation winrt-Windows.Foundation.Collections
)
echo.
echo Done. Starting the widget...
start "" pyw "%~dp0aura_widget.pyw" 2>nul || start "" pythonw "%~dp0aura_widget.pyw"
timeout /t 3 >nul
