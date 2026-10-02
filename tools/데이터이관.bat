@echo off
chcp 65001 > nul
rem 관리자 1회만 실행: 기존 업무 47건(seed_tasks.json)을 공유폴더로 이관
rem config.ini 의 data_dir 이 먼저 설정되어 있어야 합니다.
cd /d "%~dp0"
jeonjang_tasks.exe --import seed_tasks.json
