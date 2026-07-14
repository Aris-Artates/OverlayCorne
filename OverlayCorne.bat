@echo off
rem Launch the Corne overlay with no console window.
cd /d "%~dp0"
start "OverlayCorne" pythonw overlay_corne.py
