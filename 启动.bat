@echo off
rem time-is-money launcher: run app.py with pythonw (no console window)
cd /d "%~dp0"
start "" pythonw app.py
