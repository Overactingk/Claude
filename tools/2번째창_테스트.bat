@echo off
chcp 65001 > nul
rem 한 PC에서 두 번째 사용자 화면을 띄워 '동시 사용'을 시험할 때 사용 (포트 8766)
cd /d "%~dp0"
jeonjang_tasks.exe --port 8766
