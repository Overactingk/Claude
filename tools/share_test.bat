@echo off
chcp 65001 > nul
rem ============================================================
rem  공유폴더 동시쓰기 / DRM 검증용 (설치 불필요)
rem  사용법: PC 2대 이상에서 각각 이 파일을 더블클릭
rem  - 각 PC는 자기 이름의 파일에만 한 줄 추가한다 (업무관리 앱과 같은 방식)
rem  - 다른 PC가 쓴 줄이 글자 그대로 보이면 통과
rem ============================================================

set /p SHARE=테스트할 공유폴더 경로 입력 (예: \\서버\전장\업무관리테스트) :
if not exist "%SHARE%" mkdir "%SHARE%"
if not exist "%SHARE%" (
    echo [실패] 폴더를 만들거나 열 수 없습니다: %SHARE%
    pause
    exit /b 1
)

rem 내 PC 파일에 한 줄 추가 (시각 비교용으로 PC 시계도 기록)
echo %COMPUTERNAME% / %USERNAME% / %DATE% %TIME% / 한글테스트★▶>> "%SHARE%\%COMPUTERNAME%.log"
if errorlevel 1 (
    echo [실패] 쓰기 권한이 없습니다.
    pause
    exit /b 1
)

echo.
echo ===== 폴더 안의 모든 PC 기록 =====
for %%F in ("%SHARE%\*.log") do (
    echo --- %%~nxF
    type "%%F"
)
echo ==================================
echo.
echo [판정]
echo  - 다른 PC 이름의 줄이 "한글테스트★▶" 까지 정상으로 보이면: 통과
echo  - 글자가 깨지거나 읽기 오류가 나면: DRM 등으로 차단됨 (결과를 알려주세요)
echo  - 각 줄의 시각을 비교해 PC 간 시계 차이도 확인해 주세요
pause
