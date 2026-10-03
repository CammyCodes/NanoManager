@echo off
title NanoManager
cd /d "%~dp0"
"%~dp0python\python.exe" -X utf8 "%~dp0app\launcher.py" %*
if errorlevel 1 pause
