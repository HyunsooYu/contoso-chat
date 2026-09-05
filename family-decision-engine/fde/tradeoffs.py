"""부부 합의용 trade-off 질문지.

리뷰에서 초안에 없다고 지적했지만 아마 최대 가치인 항목.

이런 결정이 실제로 막히는 지점은 계산이 아니라 부부 합의다.
"장모님 댁 가까운 게 좋아" vs "출퇴근이 너무 길어" 에서 막히고, 둘 다 옳고,
비교 불가능하고, 반복된다.

이 질문지의 역할은 그 대화를 **"느낌 논쟁"에서 "가정 논쟁"으로** 바꾸는 것이다.
그리고 답을 기록해두면 다음에 다시 안 싸운다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Question:
    field: str
    prompt: str
    example: str
    converts: str

    def render(self, idx: int) -> str:
        return (
            f"\n{idx}. {self.prompt}\n"
            f"   예시) {self.example}\n"
            f"   -> preferences.{self.field} = {self.converts}"
        )


QUESTIONS = [
    Question(
        "krw_per_commute_minute_month",
        "편도 통근시간을 20분 줄이는 데 월 얼마까지 더 낼 의향이 있습니까?",
        "월 25만원까지 -> 250000 / 20 = 12500",
        "(답한 금액) / (줄이는 분)",
    ),
    Question(
        "krw_per_daycare_minute_month",
        "어린이집이 10분 더 가까우면 월 얼마의 가치가 있습니까?",
        "월 8만원 -> 80000 / 10 = 8000",
        "(답한 금액) / (줄이는 분)",
    ),
    Question(
        "krw_per_grandparent_minute_month",
        "조부모 댁이 30분 더 가까우면 월 얼마의 가치가 있습니까? "
        "(급할 때 아이를 맡길 수 있는 가치)",
        "월 4.5만원 -> 45000 / 30 = 1500",
        "(답한 금액) / (줄이는 분)",
    ),
    Question(
        "school_quality_wtp_monthly",
        "학군이 '최하'에서 '최상'으로 바뀌면 월 얼마까지 더 낼 의향이 있습니까?",
        "월 30만원 -> 300000",
        "(답한 금액)",
    ),
    Question(
        "satisfaction_wtp_monthly",
        "집 자체의 만족도(채광/구조/신축)가 '최하'에서 '최상'으로 바뀌면?",
        "월 20만원 -> 200000",
        "(답한 금액)",
    ),
    Question(
        "max_commute_minutes",
        "편도 통근시간이 몇 분을 넘으면 '아무리 좋아도 안 간다' 입니까?",
        "60분 -> 60  (이건 점수가 아니라 탈락 기준입니다)",
        "(답한 분)",
    ),
    Question(
        "max_housing_burden_ratio",
        "월 소득의 몇 %까지 주거비(이자·월세·세금·관리비, 원금 제외)로 쓸 수 있습니까?",
        "30% -> 0.30",
        "(답한 비율)",
    ),
    Question(
        "min_emergency_months",
        "소득이 끊겨도 몇 개월은 버틸 현금이 있어야 안심됩니까?",
        "6개월 -> 6",
        "(답한 개월)",
    ),
    Question(
        "max_forced_move_probability",
        "10년 안에 '원치 않는 이사'를 하게 될 확률이 몇 %를 넘으면 안 됩니까?",
        "5% -> 0.05  (아이 학기 중 이사를 피하는 것이 목표라면 낮게)",
        "(답한 확률)",
    ),
]

INTRO = """
부부 trade-off 질문지
====================================================================

가중치("육아 25%, 주거비 25%")를 지어내지 않습니다. 그건 근거를 댈 수 없고,
5%만 바꿔도 결론이 뒤집힙니다.

대신 답할 수 있는 질문을 씁니다. 아래 9개를 배우자와 함께 답하고
config/family_state.yaml 의 preferences 에 적으세요.

두 사람의 답이 다르면, 그 차이가 바로 논의해야 할 지점입니다.
그리고 답을 기록해두면 다음에 다시 싸우지 않습니다.
"""

OUTRO = """

====================================================================
답을 적은 뒤 preferences.answered_on 에 오늘 날짜를,
answered_by 에 답한 사람을 적어주세요.

아이 나이가 바뀌면 답도 바뀝니다. 만기 D-240일에 다시 하세요.
(캘린더에 이미 들어 있습니다)
"""


def render_questionnaire() -> str:
    body = "".join(q.render(i + 1) for i, q in enumerate(QUESTIONS))
    return INTRO + body + OUTRO
