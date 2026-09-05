"""전세 만기 역산 캘린더.

리뷰 결론: 이 시스템에서 가장 가치 있는 알림은 "매수 점수가 68→79로 올랐습니다"가
아니라 **만기 역산 체크리스트**다. 점수 알림은 노이즈가 되고, 노이즈가 되면
시스템 전체를 안 보게 된다.

특히 계약갱신요구권 통지 창(만기 6개월 전 ~ 2개월 전)은 **놓치면 선택지 자체가
사라지는 하드 데드라인**이다. 이걸 놓치는 손실이 이 시스템 전체 기대가치의
상당 부분을 차지한다. 캘린더 알림 2개로 해결되는 문제다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from fde.models import FamilyState
from fde.policy import PolicySet


@dataclass
class Milestone:
    days_before: int
    date: dt.date
    title: str
    detail: str
    hard: bool = False           # 놓치면 되돌릴 수 없는 항목
    done: bool = False
    category: str = "general"

    @property
    def is_past(self) -> bool:
        return self.date < dt.date.today()

    def status(self, as_of: dt.date) -> str:
        if self.done:
            return "완료"
        delta = (self.date - as_of).days
        if delta < 0:
            return f"지남 ({-delta}일 전)" + ("  ← 하드 데드라인 경과!" if self.hard else "")
        if delta == 0:
            return "오늘"
        return f"D-{delta}"


def build_calendar(state: FamilyState, policy: PolicySet) -> list[Milestone]:
    end = state.housing.contract_end
    if end is None:
        return []

    win = policy.get("lease.renewal_notice_window_months")
    notice_start_m, notice_end_m = int(win[0]), int(win[1])

    def d(days: int) -> dt.date:
        return end - dt.timedelta(days=days)

    ms: list[Milestone] = [
        Milestone(365, d(365), "보증보험 가입 상태 점검",
                  "전세보증금반환보증(HUG/HF/SGI) 가입 여부와 갱신 필요 여부 확인. "
                  "미가입이면 이 시점에 반드시 해결.",
                  hard=False, category="deposit"),
        Milestone(300, d(300), "등기부등본 재열람",
                  "선순위 근저당이 새로 잡혔는지 확인. 인터넷등기소 700원, 5분.",
                  hard=False, category="deposit"),
        Milestone(270, d(270), "전세대출 금리 재검토 / 갈아타기 가능성",
                  "만기 전에 실제로 행동 가능한 몇 안 되는 항목 중 하나.",
                  hard=False, category="finance"),
        Milestone(240, d(240), "부부 trade-off 질문지 갱신",
                  "통근/육아/학군 지불의사를 다시 답하고 preferences 갱신. "
                  "아이 나이가 바뀌면 답도 바뀐다.",
                  hard=False, category="family"),
        Milestone(notice_start_m * 30, d(notice_start_m * 30),
                  "★ 계약갱신요구권 통지 창 시작",
                  f"오늘부터 만기 {notice_end_m}개월 전까지 갱신을 요구해야 한다. "
                  f"이 창을 놓치면 갱신요구권이 소멸하고 시세대로 재계약해야 한다.",
                  hard=True, category="lease"),
        Milestone(180, d(180), "후보지 5곳 시세 추적 시작",
                  "매매·전세·월세 시세를 월 1회 기록. 임계값을 넘었는지만 확인하면 된다.",
                  hard=False, category="market"),
        Milestone(180, d(180), "은행 3곳 대출 사전조회",
                  "자체 DSR 추정은 거의 확실히 틀린다. 실제 한도를 받아 "
                  "bank_quotes 에 입력할 것.",
                  hard=False, category="finance"),
        Milestone(150, d(150), "주거자금 1차 이전 (글라이드패스)",
                  "위험자산 → 안전자산. 변동성 큰 순서대로.",
                  hard=False, category="cash"),
        Milestone(120, d(120), "임대인에게 반환/갱신 의사 서면 확인",
                  "구두 합의는 남지 않는다. 문자·내용증명 등 기록이 남는 형태로.",
                  hard=False, category="lease"),
        Milestone(notice_end_m * 30, d(notice_end_m * 30),
                  "★★ 계약갱신요구 통지 마감",
                  "이 날짜를 지나면 갱신요구권을 행사할 수 없다. "
                  "돌이킬 수 없는 유일한 항목이다.",
                  hard=True, category="lease"),
        Milestone(60, d(60), "주거자금 전액 현금화 완료",
                  "보증금·계약금 전액이 즉시 인출 가능한 상태여야 한다. 예외 없음.",
                  hard=False, category="cash"),
        Milestone(45, d(45), "이사/계약 실행 준비",
                  "이사업체·중개·대출 실행일 조율. 새 계약의 확정일자·전입신고 계획.",
                  hard=False, category="execution"),
        Milestone(0, end, "전세 만기",
                  "보증금 반환 확인. 미반환 시 즉시 임차권등기명령 검토.",
                  hard=True, category="lease"),
    ]
    ms.sort(key=lambda m: m.date)
    return ms


@dataclass
class CalendarView:
    milestones: list[Milestone]
    as_of: dt.date
    overdue_hard: list[Milestone] = field(default_factory=list)
    upcoming: list[Milestone] = field(default_factory=list)

    def render_lines(self) -> list[str]:
        out: list[str] = []
        for m in self.milestones:
            mark = "!!" if (m.hard and m.date < self.as_of and not m.done) else "  "
            out.append(
                f"{mark} {m.date.isoformat()}  {m.status(self.as_of):>14}  {m.title}"
            )
        return out


def view_calendar(
    state: FamilyState, policy: PolicySet, horizon_days: int = 120
) -> CalendarView:
    ms = build_calendar(state, policy)
    as_of = state.as_of
    overdue = [m for m in ms if m.hard and m.date < as_of and not m.done]
    upcoming = [
        m for m in ms
        if as_of <= m.date <= as_of + dt.timedelta(days=horizon_days) and not m.done
    ]
    return CalendarView(ms, as_of, overdue, upcoming)
