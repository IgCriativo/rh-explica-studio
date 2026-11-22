@echo off
title RH Explica - Estudio de Video & Narracao
cd /d "%~dp0"
echo ========================================================
echo   RH EXPLICA - ESTUDIO DE VIDEO 16:9 E NARRACAO
echo ========================================================
echo Iniciando servidor Streamlit...
echo Acesse: http://localhost:8501
python -m streamlit run app_narrador.py
pause
