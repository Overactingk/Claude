# circuit_tool — 차량 전장 회로 검증·편집 프로그램 (1차)

요구사항: [REQUIREMENTS.md](REQUIREMENTS.md)

```
[DWG] ─dwg2dxf─▶ [DXF] ─import─▶ [project.json = 회로 데이터 모델] ─verify─▶ CSV 3개
                                     ▲ 편집(gui / table-in)
[DWG] ◀─dxf2dwg─ [DXF] ◀─export──────┘   (원래 배치 유지, 속성값만 반영)
```

## 설치 (Windows)

1. Python 3.10 이상 설치
2. 이 폴더에서 `pip install -r requirements.txt`
3. DWG 자동 변환을 쓰려면 **ODA File Converter** 설치 (무료 배포, 사내 사용 라이선스 확인 필요).
   설치하지 않아도 GstarCAD 에서 `다른 이름으로 저장 → DXF` 로 직접 변환하면 된다.

## 사용 순서

```bat
:: 0) 동작 확인용 샘플 (요구사항 12장 테스트 케이스)
python -m circuit_tool sample -o sample_dxf

:: 1) DWG → DXF (ODA 설치 시)
python -m circuit_tool dwg2dxf "D:\KV405\회로도" "D:\KV405\DXF"

:: 2) DXF → 회로 데이터 (최신 리비전만, 하위 폴더 제외, 회로도 리스트 대조)
python -m circuit_tool import "D:\KV405\DXF" -o project.json --sheet-list "D:\KV405\00.KMPV_JEEP_회로도리스트_260511.xlsx"

:: 3) 화면 — 회로도 표시, 속성 편집, 검증, 퓨즈 추적 하이라이트, 참조 박스 → 짝 시트 이동
python -m circuit_tool gui project.json

:: 3') 화면 없이: 검증 → out\fuse_summary.csv, wire_detail.csv, error_report.csv
python -m circuit_tool verify project.json -o out --db parts_db

:: 4) 편집 결과 → DXF → DWG
python -m circuit_tool export project.json -o export_dxf
python -m circuit_tool dxf2dwg export_dxf export_dwg
```

표(엑셀)로 편집하려면: `table-out` → elements.csv 수정 → `table-in`.

## 작도 규칙 (블록 기반 가져오기, 방식 A)

`python -m circuit_tool template -o E_BLOCKS.dxf` 로 블록 라이브러리를 만들어 GstarCAD 에서 INSERT 해 쓴다.

| 블록 | 요소 | 속성 |
|---|---|---|
| E_FUSE | 퓨즈 (삽입점 = 출력쪽) | JBOX_NO, FUSE_NO, FUNCTION, RATING, PWR_TYPE |
| E_BOXTERM | 박스 출력 단자 | BOX, TERMINAL_NO, TERMINAL_PN |
| E_SPLICE | 분기점 | SPLICE_NO |
| E_INLINE | 인라인 커넥터 | CONN_NAME, PIN_NO, TERMINAL_PN |
| E_PIN | 유닛 핀 | DEVICE, CONN, PIN_NO, PIN_FUNC, LOAD_CURRENT, TERMINAL_PN |
| E_SHEETREF | 시트 참조 | LINK_ID, TARGET_SHEET, TARGET_DEVICE, TARGET_CONN, TARGET_PIN, DIRECTION |
| E_WIRE_LABEL | 전선 라벨 (선 바로 위) | WIRE_NO, MATERIAL, SQ, COLOR, ENV |

- **블록 삽입점 = 접속점.** 전선 끝점을 삽입점에 정확히 맞춘다 (허용오차 `--tol`, 기본 0.5).
- 같은 점에 놓인 블록끼리는 전선 없이 연결된 것으로 본다 (예: 퓨즈 + 박스 단자 + 참조 박스).
- 전선은 `WIRE` 레이어의 LINE / LWPOLYLINE 만. 선은 끝점끼리만 연결 (중간 통과는 연결 아님).
- 3갈래 이상은 반드시 E_SPLICE. 없으면 오류를 내되 추적은 계속한다.
- 같은 CONN_NAME + PIN_NO 의 E_INLINE, 같은 LINK_ID 의 E_SHEETREF 는 서로 통과 연결된다.
- PIN_FUNC: `B+ IG ACC GND SIG`. LOAD_CURRENT 는 전원 핀에만, 병렬 전원 핀은 한 핀에 총합·나머지는 `0`.
- ENV(실내/엔진룸)를 비우면 DB에 해당 재질·SQ 가 한 행일 때만 판정, 여러 행이면 '판정 불가'.

## 부품 DB (`parts_db/`)

| 파일 | 열 |
|---|---|
| wire_ampacity.csv | MATERIAL, SQ, ENV, AMPACITY_A, SOURCE |
| terminals.csv | TERMINAL_PN, RATING_A, SQ_MIN, SQ_MAX, SOURCE |
| fuse.csv | ITEM(MARGIN / STD_RATING), VALUE, SOURCE |

**동봉된 값은 전부 가상값(SAMPLE)이다. 사내 기준·데이터시트 값으로 교체해야 한다.**

## 판정 (OK / NG / 판정 불가)

| 판정 | 조건 |
|---|---|
| 퓨즈 | 용량 ≥ 하류 부하 합 × MARGIN |
| 전선 | 하류 모든 전선 구간 허용전류 ≥ 퓨즈 용량 |
| 단자 | 전선 양 끝(직접 붙은 박스 단자·인라인·핀 포함) 정격 ≥ 퓨즈 용량, SQ 수용 범위 |
| 전원 종류 | 핀 PIN_FUNC = 퓨즈 PWR_TYPE (불일치 → error_report) |
| 연결 | 추적 안 되는 전원 핀, 전류 미입력, 참조 짝 없음·중복·불일치, Splice 누락, 미연결 선, 라벨 없음 |

## 기존 도면 (블록 없는 그림) 에 대해

현재 회로도처럼 선·사각형·글자로만 된 도면은 연결 정보가 없으므로 **방식 A 로는 회로가 만들어지지 않는다.**
`scan-text` 는 텍스트를 패턴으로 해석해 *후보* 목록(전선 `55 (1.0 LB)`, 퓨즈 `IMMO F11 10A`,
참조 박스 `BCM G-22P W(G13,START,RLY30) 07`)과 미해석 목록만 CSV 로 낸다. 연결 추론·검토 화면은 2차 범위.

## 1차 범위에서 하지 않는 것 / 가정

- 모델에서 도면을 새로 그리는 기능 (2차). 내보내기는 원본 DXF 속성값 수정만.
- 동적 블록(이름이 `*U…`)은 인식하지 않음 → 일반 블록으로 작도.
- 릴레이·스위치 통과, GND 회로 (2차).
- 참조 박스 시트번호 `07` ↔ 도면번호 690**07** 대응은 **가정**(요구사항 13장 미결정). 불일치 시 오류로 표시.
- ECU 전원 입력은 핀(종점)으로 처리.

## 테스트

```
python -m pytest -q tests
```
