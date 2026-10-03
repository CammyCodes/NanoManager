@echo off
title NanoManager (phone access)
cd /d "%~dp0"
"%~dp0python\python.exe" -X utf8 "%~dp0app\launcher.py" --share %*
if errorlevel 1 pause
