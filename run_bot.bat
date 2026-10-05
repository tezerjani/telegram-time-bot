@echo off
cd /d "C:\Users\User\Desktop\telegram-assistant"
:loop
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" main.py >> "C:\Users\User\Desktop\telegram-assistant\bot_runner.log" 2>&1
timeout /t 5 /nobreak >nul
goto loop
