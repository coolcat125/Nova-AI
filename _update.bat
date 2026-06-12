@echo off
title Nova Updater
timeout /t 1 /nobreak >nul
copy /y "C:\Users\Nicholas\AppData\Local\Temp\nova_update_c42m9pbu\Nova.exe" "C:\Users\Nicholas\OneDrive\Computer Science\claude projects\nova-desktop\Nova.exe" >nul 2>&1
:retry_rm
if exist "C:\Users\Nicholas\AppData\Local\Temp\nova_update_c42m9pbu" (
  rmdir /s /q "C:\Users\Nicholas\AppData\Local\Temp\nova_update_c42m9pbu" >nul 2>&1
  if exist "C:\Users\Nicholas\AppData\Local\Temp\nova_update_c42m9pbu" (
    timeout /t 1 /nobreak >nul
    goto retry_rm
  )
)
start "" "C:\Users\Nicholas\AppData\Local\Python\pythoncore-3.14-64\python.exe" "C:\Users\Nicholas\OneDrive\Computer Science\claude projects\nova-desktop\main.py"
exit