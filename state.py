from typing import TypedDict


class ConversationState(TypedDict):
    current_stage: str   # node name, e.g. "idle", "q1", "oximeter_reading"
    page_id: str         # UI page identifier, e.g. "01"
    robot_response: str
    answers: dict        # {"q1": "...", "q2": "skipped", "q3": "..."}
    readings: dict       # {"oximeter_hr": 72, "oximeter_spo2": 98, "bp": "125/82", "scale": 74.2}
    retry_stage: str     # which reading stage to return to after sorry
    retry_count: int     # consecutive device-failure retries
