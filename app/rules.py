"""업무 상태 판정·입력 점검 규칙 (화면·대시보드·엑셀·테스트 공통)."""

from datetime import date

from app.store import parse_date

# 상태 값 (화면 배지·색상·필터에 공통 사용)
DONE, OVERDUE, DUE_SOON, IN_PROGRESS = "완료", "지연", "임박", "진행중"
DUE_SOON_DAYS = 3  # 노랑 표시 기준 (지시서: 3일 이내 마감)


def task_status(target: date | None, done: date | None, today: date) -> str:
    """업무 상태 판정. today를 인자로 받아 테스트에서 날짜를 고정할 수 있게 함."""
    if done is not None:
        return DONE
    if target is None:  # 목표 없음 → 판정 불가, 입력점검에서 따로 표시
        return IN_PROGRESS
    days_left = (target - today).days
    if days_left < 0:
        return OVERDUE
    if days_left <= DUE_SOON_DAYS:
        return DUE_SOON
    return IN_PROGRESS


def status_of(task: dict, today: date) -> str:
    return task_status(parse_date(task["target"]), parse_date(task["done_date"]), today)


def days_left(task: dict, today: date) -> int | None:
    target = parse_date(task["target"])
    return None if target is None else (target - today).days


def input_issues(task: dict, today: date) -> list[str]:
    """지시서 5장-8 '입력 점검' 항목. 데이터는 고치지 않고 표시만 한다."""
    issues = []
    created, target = parse_date(task["created_date"]), parse_date(task["target"])
    if created is None:
        issues.append("작성날짜 없음")
    if target is None:
        issues.append("목표 없음")
    if created and target and target < created:
        issues.append("목표가 작성일보다 앞")
    if not task["project"]:
        issues.append("프로젝트 없음")
    if status_of(task, today) == OVERDUE:
        issues.append("지연")
    return issues


def sort_key(task: dict) -> tuple:
    """기본 정렬: 미완료 먼저 → 목표일 빠른 순(목표 없음은 뒤) → 번호."""
    return (task["done_date"] is not None, task["target"] or "9999-12-31", task["no"])


def can_edit(task: dict, me: str, is_admin: bool) -> bool:
    """수정 권한: 주담당·협업자·관리자. ('전장' 업무는 사실상 관리자만)"""
    return is_admin or me == task["owner"] or me in task["collaborators"]
