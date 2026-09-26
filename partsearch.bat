@echo off
rem Part Search - start the window with KiCad's bundled Python (it ships wxPython).
rem   partsearch.bat            window, no console
rem   partsearch.bat --console  same, console stays open to show Python errors (debugging)
set "KPY=C:\Program Files\KiCad\10.0\bin"
if /I "%~1"=="--console" (
    "%KPY%\python.exe" "%~dp0partsearch.pyw"
    pause
) else (
    start "" "%KPY%\pythonw.exe" "%~dp0partsearch.pyw"
)
