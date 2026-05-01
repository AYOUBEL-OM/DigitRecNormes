"""
Durées autorisées pour les réponses orales (cohérent avec `Frontend/src/oral-interview/constants/oralTiming.ts`).
"""

ORAL_PREP_TIME = 7
ORAL_ANSWER_TIME_DEFAULT = 60
ORAL_ANSWER_MARGIN_SECONDS = 5

QUESTION_TIME_INTRO = 45
QUESTION_TIME_NORMAL = 60
QUESTION_TIME_ADVANCED = 75


def max_answer_seconds_for_question(question_order_1based: int, question_text: str) -> int:
    """
    `question_order` : 1-based (aligné API).
    Intro : ordres 1–3. Sinon heuristique « avancé » sur le libellé.
    """
    idx0 = int(question_order_1based) - 1
    if idx0 < 3:
        return QUESTION_TIME_INTRO
    t = (question_text or "").lower()
    if any(
        x in t
        for x in (
            "stratég",
            "strateg",
            "architecture",
            "due diligence",
            "restructuration",
            "transformation majeure",
            "m&a",
            "maîtrise",
            "pilotage",
            "vision",
        )
    ):
        return QUESTION_TIME_ADVANCED
    return QUESTION_TIME_NORMAL


def max_answer_seconds_with_margin(question_order_1based: int, question_text: str) -> int:
    return max_answer_seconds_for_question(question_order_1based, question_text) + ORAL_ANSWER_MARGIN_SECONDS
