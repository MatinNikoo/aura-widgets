@echo off
title Remove Aura
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\remove.ps1"
pause
