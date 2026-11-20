@echo off
chcp 65001 > nul
title Willy (Modo Depuracao)
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" willy.py
pause
