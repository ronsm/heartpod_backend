"""
LangGraph POC for Human-Robot Conversation
Full 17-state state machine with branching logic, questionnaire handling,
device reading queues with timeouts, sorry/retry flow, and recap.

HTTP server integration (replaces mock_backend.py):
  GET  /state  → {"page_id": N, "data": {...}}   – polled by the Android app
  POST /action → {"action": "...", "data": {...}} – button presses from the app

Button actions are forwarded as plain text strings into the same LLM pipeline
that handles voice input, so "confirm", "skip", "ready", etc. are interpreted
exactly as if the user had typed them.
"""

import argparse
import json
import os
import queue
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TypedDict
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

# ---------------------------------------------------------------------------
# HTTP shared state — read by GET /state, written by the robot's node functions
# ---------------------------------------------------------------------------
_http_state: dict = {"page_id": 1, "data": {}}
_http_state_lock = threading.Lock()

# Actions from the Android app are placed here; _ask_user() blocks on this queue
_action_queue: queue.Queue = queue.Queue()

DEFAULT_PORT = 8000


class _HttpHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the Android app comms protocol."""

    def do_GET(self):
        if self.path != "/state":
            self.send_response(404)
            self.end_headers()
            return
        with _http_state_lock:
            body = json.dumps(_http_state).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Maps UI action keywords to the natural-language phrases the LLM understands.
    # Questionnaire answers are passed through as-is (already natural language).
    _ACTION_TEXT = {
        "start":    "Start Self-Screening",
        "confirm":  "yes",
        "accept":   "yes",
        "ready":    "ready",
        "continue": "continue",
        "skip":     "skip",
        "retry":    "retry",
        "exit":     "no",
        "finish":   "done",
    }

    def do_POST(self):
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        action = body.get("action", "")
        data = body.get("data", {})
        # Answers carry the full option text; everything else maps to a typed phrase.
        if action == "answer":
            text = data.get("answer", action)
        else:
            text = self._ACTION_TEXT.get(action, action)
        if text:
            _action_queue.put(text)
            print(f"\n  [app] '{text}'" + (f"  ({action})" if action != text else ""))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress per-request logs

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
READING_TIMEOUT = 30  # seconds before device reading times out
MAX_RETRIES = 3  # max consecutive sorry retries before returning to idle
LLM_MODEL = "gpt-3.5-turbo"
LLM_TEMPERATURE = 0.7

# ---------------------------------------------------------------------------
# PAGE_CONFIG – single source of all static strings
# ---------------------------------------------------------------------------
PAGE_CONFIG = {
    "idle": {
        "page_id": "01",
        "message": "Hello, welcome to the self-screening health check pod. If you would like to start a self-screening, please choose 'Start Self-Screening' on my screen.",
        "action_context": "confirming whether they want to begin the health check (yes to start, no to decline)",
    },
    "welcome": {
        "page_id": "02",
        "message": (
            "I’m Temi, your digital health assistant. I'll guide you step-by-step through the self-screening process and provide you with a copy of your results to take away. Before we start, please take a seat and make yourself comfortable. If you are wearing a jacket or coat, you can remove it now - it will make the process easier. I will ask a few general lifestyle questions to give the clinical team some background. You can choose to skip any question, if you wish. Let me know if you wish to continue."
        ),
        "action_context": "confirming they consent to start the session",
    },
    "q1": {
        "page_id": "03",
        "message": (
            "Q1. How frequently do you smoke?\n"
            "  1. I previously smoked but no longer do\n"
            "  2. I do not and have never smoked\n"
            "  3. Occasionally (e.g. weekly or monthly)\n"
            "  4. A few times a day\n"
            "  5. Many times per day"
        ),
        "options": [
            "I previously smoked but no longer do",
            "I do not and have never smoked",
            "Occasionally (e.g. weekly or monthly)",
            "A few times a day",
            "Many times per day",
        ],
        "action_context": "answering a question about their smoking frequency",
    },
    "q2": {
        "page_id": "04",
        "message": (
            "Q2. How often do you exercise?\n"
            "  1. Never\n"
            "  2. Rarely (a few times a month)\n"
            "  3. Sometimes (1-2 times a week)\n"
            "  4. Often (3-4 times a week)\n"
            "  5. Daily"
        ),
        "options": [
            "Never",
            "Rarely (a few times a month)",
            "Sometimes (1-2 times a week)",
            "Often (3-4 times a week)",
            "Daily",
        ],
        "action_context": "answering a question about their exercise frequency",
    },
    "q3": {
        "page_id": "05",
        "message": (
            "Q3. How many units of alcohol do you drink per week?\n"
            "  1. None\n"
            "  2. 1-7 units\n"
            "  3. 8-14 units\n"
            "  4. 15-21 units\n"
            "  5. More than 21 units"
        ),
        "options": [
            "None",
            "1-7 units",
            "8-14 units",
            "15-21 units",
            "More than 21 units",
        ],
        "action_context": "answering a question about their weekly alcohol consumption",
    },
    "measure_intro": {
        "page_id": "06",
        "message": (
            "Great, thank you for answering those questions! "
            "Now we'll take three quick measurements: an oximeter reading, a blood pressure reading, "
            "and your weight. Just say 'continue' when you're happy to begin."
        ),
        "action_context": "confirming they are ready to start the measurements",
    },
    "oximeter_intro": {
        "page_id": "07",
        "message": (
            "Remain seated, and breath comfortably. Now, place your index finger inside the oximeter, with your fingernail facing upwards towards the ceiling. Keep your hand resting on the table. Say 'ready' when it's in place."
        ),
        "action_context": "confirming the oximeter is clipped onto their finger",
    },
    "oximeter_reading": {
        "page_id": "08",
        "message": "Taking oximeter reading... please stay still.",
        "action_context": "waiting for oximeter device data",
    },
    "oximeter_done": {
        "page_id": "09",
        "message": "Great. Thank you! I’ve recorded your blood oxygen and heart rate information. Next, we will measure your weight and height. Say 'continue' when you're ready for the next measurement.",
        "action_context": "confirming they are ready to continue to blood pressure",
    },
    "bp_intro": {
        "page_id": "10",
        "message": (
            "Next, we'll measure your blood pressure. Please put on the blood pressure cuff "
            "and sit comfortably with your arm resting at heart level. Say 'ready' when set."
        ),
        "action_context": "confirming the blood pressure cuff is on and they are ready",
    },
    "bp_reading": {
        "page_id": "11",
        "message": "Measuring now. Please relax and keep still.",
        "action_context": "waiting for blood pressure device data",
    },
    "bp_done": {
        "page_id": "12",
        "message": "Great. Thank you! I've recorded your blood pressure. Next, we will measure your oxygen level and pulse. Say 'continue' when you're ready for the final measurement.",
        "action_context": "confirming they are ready to continue to the scale",
    },
    "scale_intro": {
        "page_id": "13",
        "message": (
            "Finally, we'll measure your weight. Please step onto the scale, which is over here on your [left/right]. Once you are on the scale, stand straight and as still as possible. Say 'ready' when you're on the scale."
        ),
        "action_context": "confirming they are standing on the scale",
    },
    "scale_reading": {
        "page_id": "14",
        "message": "Taking weight reading... please stand still.",
        "action_context": "waiting for scale device data",
    },
    "scale_done": {
        "page_id": "15",
        "message": "•	“Great. Thank you! I've recorded your height and weight. You can now step off the scale and sit back down. Say 'continue' to see your summary.",
        "action_context": "confirming they are ready to see the recap",
    },
    "recap": {
        "page_id": "16",
        "message": "We have now completed all the measurements. Your results are shown on my screen. Please wait a moment while I also print you a paper copy to take away.",
        "action_context": "reviewing their health check summary",
    },
    "sorry": {
        "page_id": "17",
        "message_device": "Sorry, we weren't able to get a reading. Would you like to try again?",
        "message_invalid": "Sorry, I didn't quite catch your answer. Could you try again?",
        "message_reject": "No problem. Let me know when you'd like to try again.",
        "action_context": "deciding whether to retry the failed step",
    },
}


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------
class ConversationState(TypedDict):
    current_stage: str  # node name
    page_id: str  # UI page ID string, e.g. "01"
    user_input: str
    robot_response: str
    answers: dict  # {"q1": "...", "q2": "...", "q3": "..."}
    readings: (
        dict  # {"oximeter_hr": 72, "oximeter_spo2": 98, "bp": "125/82", "scale": 74.2}
    )
    retry_stage: str  # stage to return to from sorry
    retry_count: int  # consecutive sorry retries
    should_continue: bool


# ---------------------------------------------------------------------------
# Device reading queue
# ---------------------------------------------------------------------------
device_queue: queue.Queue = queue.Queue()


def _generate_value(device: str):
    """Generate a realistic fake reading for the given device."""
    if device == "oximeter":
        return {"hr": random.randint(60, 100), "spo2": random.randint(95, 100)}
    elif device == "bp":
        systolic = random.randint(110, 140)
        diastolic = random.randint(70, 90)
        return f"{systolic}/{diastolic}"
    elif device == "scale":
        return round(random.uniform(50, 120), 1)
    return None


def simulate_reading(device: str, delay: float = 2.0):
    """Push a fake reading after `delay` seconds. Replace with real hardware hook."""

    def _push():
        value = _generate_value(device)
        device_queue.put({"device": device, "value": value})

    threading.Timer(delay, _push).start()


# ---------------------------------------------------------------------------
# Main graph class
# ---------------------------------------------------------------------------
class HealthRobotGraph:

    def __init__(self):
        self.llm = ChatOpenAI(model=LLM_MODEL, temperature=LLM_TEMPERATURE)
        self.graph = self.build_graph()

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def should_proceed(self, user_input: str, action_context: str) -> bool:
        """Return True if the user confirms they are ready/consent."""
        messages = [
            SystemMessage(
                content=(
                    f"You are analysing user input in a health sensor conversation.\n"
                    f"The user was asked to complete this action: {action_context}\n\n"
                    "Determine if the user is indicating they are READY or CONSENTING to proceed.\n"
                    "They ARE ready/consenting if they:\n"
                    "- Say yes, ready, ok, sure, go ahead, let's go, done, continue, begin, start, etc.\n"
                    "- State they've completed the requested action.\n"
                    "- Say 'start self-screening'.\n"
                    "- State that they agree or accept.\n"
                    "Do not be too fussy distinguishing between 'ready' and 'continue'.\n"
                    "They are NOT ready if they are asking a question, requesting help, or declining.\n\n"
                    "Respond with ONLY 'YES' or 'NO'."
                )
            ),
            HumanMessage(
                content=f"User said: {user_input}\n\nAre they ready/consenting? (YES/NO)"
            ),
        ]
        response = self.llm.invoke(messages)
        return "YES" in response.content.upper()

    def handle_general_question(self, user_input: str, context: str) -> str:
        """Handle off-topic questions or diversions within the current state."""
        messages = [
            SystemMessage(
                content=(
                    "You are a friendly health monitoring robot assistant.\n"
                    f"Current context: {context}\n\n"
                    "The user said something that isn't a direct confirmation to proceed. "
                    "Answer their question or respond to their comment helpfully and briefly, "
                    "then gently remind them about the current task. Keep your response concise (2-3 sentences max)."
                )
            ),
            HumanMessage(content=user_input),
        ]
        response = self.llm.invoke(messages)
        return response.content

    def user_wants_to_skip(self, user_input: str) -> bool:
        """Return True if the user wants to skip the current question."""
        messages = [
            SystemMessage(
                content=(
                    "The user is answering a health questionnaire question and may choose to skip it.\n"
                    "Did they indicate they want to skip? "
                    "Skip indicators include: 'skip', 'pass', 'next', 'I'd rather not', "
                    "'prefer not to say', 'no thanks', 'move on', etc.\n"
                    "Respond with ONLY 'YES' if they want to skip, or 'NO' if they are attempting to answer."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self.llm.invoke(messages)
        return "YES" in response.content.upper()

    def validate_answer(self, user_input: str, question_key: str):
        """
        Use LLM to map free-text to one of the defined options.
        Returns the matched option string or None.
        """
        options = PAGE_CONFIG[question_key]["options"]
        options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        messages = [
            SystemMessage(
                content=(
                    "You are matching a user's free-text answer to the closest option from a fixed list.\n"
                    f"The options are:\n{options_text}\n\n"
                    "If the user's answer clearly maps to one of these options (by number, keyword, or meaning), "
                    "reply with ONLY the exact option text.\n"
                    "If the answer is ambiguous, off-topic, or does not match any option, reply with ONLY the word NONE."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self.llm.invoke(messages)
        result = response.content.strip()
        if result.upper() == "NONE":
            return None
        # Verify the returned text is actually one of our options
        for opt in options:
            if opt.lower() in result.lower() or result.lower() in opt.lower():
                return opt
        return None

    def retry_or_give_up(self, user_input: str) -> bool:
        """Return True if user wants to retry, False if giving up."""
        messages = [
            SystemMessage(
                content=(
                    "The user was asked whether they want to retry a failed step or give up.\n"
                    "Reply with ONLY 'RETRY' if they want to try again, or 'GIVEUP' if they want to stop."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self.llm.invoke(messages)
        return "RETRY" in response.content.upper()

    # ------------------------------------------------------------------
    # Node functions
    # ------------------------------------------------------------------

    def _set_page(
        self, state: ConversationState, stage: str, message: str
    ) -> ConversationState:
        """Utility: update stage, page_id, and robot_response from PAGE_CONFIG."""
        state["current_stage"] = stage
        state["page_id"] = PAGE_CONFIG[stage]["page_id"]
        state["robot_response"] = message
        # Push the new page to the HTTP state so the Android app picks it up.
        page_id_int = int(state["page_id"])
        http_data = self._build_data(state)
        with _http_state_lock:
            _http_state["page_id"] = page_id_int
            _http_state["data"] = http_data
        return state

    def _build_data(self, state: ConversationState) -> dict:
        """Build the data payload for the current stage to send via GET /state."""
        stage = state["current_stage"]
        r = state.get("readings", {})

        if stage == "idle":
            return {}
        elif stage == "welcome":
            return {"message": state["robot_response"]}
        elif stage in ("q1", "q2", "q3"):
            cfg = PAGE_CONFIG[stage]
            # First line of the message is the question text
            question = cfg["message"].split("\n")[0]
            return {
                "question": question,
                "options": json.dumps(cfg["options"]),
            }
        elif stage == "measure_intro":
            return {"message": state["robot_response"]}
        elif stage == "oximeter_intro":
            return {"device": "oximeter"}
        elif stage == "oximeter_reading":
            return {"message": state["robot_response"]}
        elif stage == "oximeter_done":
            return {
                "value": f"{r.get('oximeter_hr', '?')} bpm / {r.get('oximeter_spo2', '?')}%",
                "unit": "HR / SpO2",
            }
        elif stage == "bp_intro":
            return {"device": "blood pressure monitor"}
        elif stage == "bp_reading":
            return {"message": state["robot_response"]}
        elif stage == "bp_done":
            return {"value": r.get("bp", "?"), "unit": "mmHg"}
        elif stage == "scale_intro":
            return {"device": "scale"}
        elif stage == "scale_reading":
            return {"message": state["robot_response"]}
        elif stage == "scale_done":
            return {"value": str(r.get("scale", "?")), "unit": "kg"}
        elif stage == "recap":
            return {}
        elif stage == "sorry":
            return {"message": state["robot_response"]}
        else:
            return {}

    def idle_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "idle", PAGE_CONFIG["idle"]["message"])

    def welcome_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "welcome", PAGE_CONFIG["welcome"]["message"])

    def q1_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "q1", PAGE_CONFIG["q1"]["message"])

    def q2_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "q2", PAGE_CONFIG["q2"]["message"])

    def q3_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "q3", PAGE_CONFIG["q3"]["message"])

    def measure_intro_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(
            state, "measure_intro", PAGE_CONFIG["measure_intro"]["message"]
        )

    def oximeter_intro_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(
            state, "oximeter_intro", PAGE_CONFIG["oximeter_intro"]["message"]
        )

    def oximeter_reading_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(
            state, "oximeter_reading", PAGE_CONFIG["oximeter_reading"]["message"]
        )

    def oximeter_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        msg = (
            f"Oximeter reading complete!\n"
            f"  Heart Rate: {r.get('oximeter_hr', '?')} bpm\n"
            f"  SpO2: {r.get('oximeter_spo2', '?')}%\n\n"
            "Say 'continue' when you're ready for the next measurement."
        )
        return self._set_page(state, "oximeter_done", msg)

    def bp_intro_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "bp_intro", PAGE_CONFIG["bp_intro"]["message"])

    def bp_reading_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "bp_reading", PAGE_CONFIG["bp_reading"]["message"])

    def bp_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        msg = (
            f"Blood pressure reading complete!\n"
            f"  Blood Pressure: {r.get('bp', '?')} mmHg\n\n"
            "Say 'continue' when you're ready for the final measurement."
        )
        return self._set_page(state, "bp_done", msg)

    def scale_intro_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(
            state, "scale_intro", PAGE_CONFIG["scale_intro"]["message"]
        )

    def scale_reading_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(
            state, "scale_reading", PAGE_CONFIG["scale_reading"]["message"]
        )

    def scale_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        msg = (
            f"Weight reading complete!\n"
            f"  Weight: {r.get('scale', '?')} kg\n\n"
            "Say 'continue' to see your summary."
        )
        return self._set_page(state, "scale_done", msg)

    def recap_node(self, state: ConversationState) -> ConversationState:
        a = state["answers"]
        r = state["readings"]
        lines = [PAGE_CONFIG["recap"]["message"], ""]
        lines.append("Questionnaire answers:")
        lines.append(f"  Smoking:   {a.get('q1', 'not answered')}")
        lines.append(f"  Exercise:  {a.get('q2', 'not answered')}")
        lines.append(f"  Alcohol:   {a.get('q3', 'not answered')}")
        lines.append("")
        lines.append("Measurements:")
        lines.append(f"  Heart Rate: {r.get('oximeter_hr', '?')} bpm")
        lines.append(f"  SpO2:       {r.get('oximeter_spo2', '?')}%")
        lines.append(f"  BP:         {r.get('bp', '?')} mmHg")
        lines.append(f"  Weight:     {r.get('scale', '?')} kg")
        lines.append("")
        lines.append(
            "Thank you for completing your health check! Say anything to return to the start."
        )
        return self._set_page(state, "recap", "\n".join(lines))

    def sorry_node(self, state: ConversationState) -> ConversationState:
        """Triggered only by a device reading failure (timeout)."""
        msg = PAGE_CONFIG["sorry"]["message_device"]
        msg += f"\n(Retry {state.get('retry_count', 0)}/{MAX_RETRIES})"
        return self._set_page(state, "sorry", msg)

    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    def build_graph(self) -> StateGraph:
        workflow = StateGraph(ConversationState)

        workflow.add_node("idle", self.idle_node)
        workflow.add_node("welcome", self.welcome_node)
        workflow.add_node("q1", self.q1_node)
        workflow.add_node("q2", self.q2_node)
        workflow.add_node("q3", self.q3_node)
        workflow.add_node("measure_intro", self.measure_intro_node)
        workflow.add_node("oximeter_intro", self.oximeter_intro_node)
        workflow.add_node("oximeter_reading", self.oximeter_reading_node)
        workflow.add_node("oximeter_done", self.oximeter_done_node)
        workflow.add_node("bp_intro", self.bp_intro_node)
        workflow.add_node("bp_reading", self.bp_reading_node)
        workflow.add_node("bp_done", self.bp_done_node)
        workflow.add_node("scale_intro", self.scale_intro_node)
        workflow.add_node("scale_reading", self.scale_reading_node)
        workflow.add_node("scale_done", self.scale_done_node)
        workflow.add_node("recap", self.recap_node)
        workflow.add_node("sorry", self.sorry_node)

        workflow.set_entry_point("idle")

        # Simple linear edges (no branching)
        workflow.add_edge("idle", "welcome")
        workflow.add_edge("measure_intro", "oximeter_intro")
        workflow.add_edge("oximeter_intro", "oximeter_reading")
        workflow.add_edge("oximeter_done", "bp_intro")
        workflow.add_edge("bp_intro", "bp_reading")
        workflow.add_edge("bp_done", "scale_intro")
        workflow.add_edge("scale_intro", "scale_reading")
        workflow.add_edge("recap", END)

        # Conditional edges are handled in the run() loop directly;
        # the graph topology below represents them symbolically.
        workflow.add_edge("welcome", "q1")
        workflow.add_edge("q1", "q2")
        workflow.add_edge("q2", "q3")
        workflow.add_edge("q3", "measure_intro")
        workflow.add_edge("oximeter_reading", "oximeter_done")
        workflow.add_edge("bp_reading", "bp_done")
        workflow.add_edge("scale_reading", "scale_done")
        workflow.add_edge("scale_done", "recap")
        workflow.add_edge("sorry", END)

        return workflow.compile()

    # ------------------------------------------------------------------
    # Interactive run loop
    # ------------------------------------------------------------------

    def _print_robot(self, msg: str, page_id: str = None):
        if page_id:
            print(f"\n[Page {page_id}] Robot: {msg}\n")
        else:
            print(f"\nRobot: {msg}\n")

    def _ask_user(self) -> str:
        """Block until the Android app posts an action, then return it as text."""
        return _action_queue.get()

    def _wait_for_proceed(self, action_context: str):
        """Block until user confirms ready. Handles diversions inline via LLM."""
        while True:
            user_input = self._ask_user()
            if self.should_proceed(user_input, action_context):
                return
            response = self.handle_general_question(user_input, action_context)
            self._print_robot(response)

    def _do_device_reading(self, device: str, state: ConversationState) -> bool:
        """
        Attempt to get a reading from device_queue within READING_TIMEOUT seconds.
        Populates state["readings"] on success. Returns True on success, False on timeout.
        Automatically triggers simulate_reading() for demo purposes.
        """
        print(f"  [Waiting for {device} device data (timeout={READING_TIMEOUT}s)...]")
        simulate_reading(device, delay=2.0)  # remove this line when using real hardware
        try:
            data = device_queue.get(timeout=READING_TIMEOUT)
            print(f"  [Device data received: {data}]")
            if device == "oximeter":
                state["readings"]["oximeter_hr"] = data["value"]["hr"]
                state["readings"]["oximeter_spo2"] = data["value"]["spo2"]
            elif device == "bp":
                state["readings"]["bp"] = data["value"]
            elif device == "scale":
                state["readings"]["scale"] = data["value"]
            return True
        except queue.Empty:
            print(f"  [Timeout: no data received from {device}]")
            return False

    def run(self):
        print("=" * 60)
        print("HeartPod")
        print("=" * 60)
        print("(Type 'quit' or 'exit' to end)\n")

        while True:  # outer loop allows returning to idle
            state: ConversationState = {
                "current_stage": "idle",
                "page_id": PAGE_CONFIG["idle"]["page_id"],
                "user_input": "",
                "robot_response": "",
                "answers": {},
                "readings": {},
                "retry_stage": "",
                "retry_count": 0,
                "should_continue": False,
            }

            # ── idle ──────────────────────────────────────────────────
            state = self.idle_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["idle"]["action_context"])

            # ── welcome ───────────────────────────────────────────────
            state = self.welcome_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["welcome"]["action_context"])

            # ── questionnaire (Q1 / Q2 / Q3) ─────────────────────────
            for qkey in ("q1", "q2", "q3"):
                node_fn = getattr(self, f"{qkey}_node")
                state = node_fn(state)
                self._print_robot(state["robot_response"], state["page_id"])
                while True:
                    user_input = self._ask_user()
                    if self.user_wants_to_skip(user_input):
                        state["answers"][qkey] = "skipped"
                        print(f"  [Question {qkey} skipped]")
                        break
                    matched = self.validate_answer(user_input, qkey)
                    if matched:
                        state["answers"][qkey] = matched
                        print(f"  [Recorded answer for {qkey}: {matched}]")
                        break
                    else:
                        # Inline re-prompt – no state change
                        opts = "\n".join(
                            f"  {i+1}. {o}"
                            for i, o in enumerate(PAGE_CONFIG[qkey]["options"])
                        )
                        self._print_robot(
                            f"I didn't quite catch that. Please choose one of:\n{opts}"
                        )

            # ── measure_intro ─────────────────────────────────────────
            state = self.measure_intro_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["measure_intro"]["action_context"])

            # ── oximeter ──────────────────────────────────────────────
            state = self.oximeter_intro_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["oximeter_intro"]["action_context"])

            # Reading loop with sorry/retry
            oximeter_done = False
            while not oximeter_done:
                state = self.oximeter_reading_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                success = self._do_device_reading("oximeter", state)
                if success:
                    state = self.oximeter_done_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    self._wait_for_proceed(
                        PAGE_CONFIG["oximeter_done"]["action_context"]
                    )
                    oximeter_done = True
                else:
                    state["retry_count"] += 1

                    state["retry_stage"] = "oximeter_reading"
                    state = self.sorry_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    if state["retry_count"] >= MAX_RETRIES:
                        self._print_robot(
                            "Maximum retries reached. Returning to start."
                        )
                        break
                    user_input = self._ask_user()
                    if not self.retry_or_give_up(user_input):
                        self._print_robot("No problem. Returning to start.")
                        break
            if not oximeter_done:
                continue

            # ── blood pressure ────────────────────────────────────────
            state = self.bp_intro_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["bp_intro"]["action_context"])

            bp_done = False
            while not bp_done:
                state = self.bp_reading_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                success = self._do_device_reading("bp", state)
                if success:
                    state = self.bp_done_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    self._wait_for_proceed(PAGE_CONFIG["bp_done"]["action_context"])
                    bp_done = True
                else:
                    state["retry_count"] += 1

                    state["retry_stage"] = "bp_reading"
                    state = self.sorry_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    if state["retry_count"] >= MAX_RETRIES:
                        self._print_robot(
                            "Maximum retries reached. Returning to start."
                        )
                        break
                    user_input = self._ask_user()
                    if not self.retry_or_give_up(user_input):
                        self._print_robot("No problem. Returning to start.")
                        break
            if not bp_done:
                continue

            # ── scale ─────────────────────────────────────────────────
            state = self.scale_intro_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["scale_intro"]["action_context"])

            scale_done = False
            while not scale_done:
                state = self.scale_reading_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                success = self._do_device_reading("scale", state)
                if success:
                    state = self.scale_done_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    self._wait_for_proceed(PAGE_CONFIG["scale_done"]["action_context"])
                    scale_done = True
                else:
                    state["retry_count"] += 1

                    state["retry_stage"] = "scale_reading"
                    state = self.sorry_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    if state["retry_count"] >= MAX_RETRIES:
                        self._print_robot(
                            "Maximum retries reached. Returning to start."
                        )
                        break
                    user_input = self._ask_user()
                    if not self.retry_or_give_up(user_input):
                        self._print_robot("No problem. Returning to start.")
                        break
            if not scale_done:
                continue

            # ── recap ─────────────────────────────────────────────────
            state = self.recap_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._ask_user()  # wait for any input then loop back to idle


def main():
    parser = argparse.ArgumentParser(description="HealthHub LangGraph backend with HTTP interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port for the HTTP server (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set!")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return

    server = HTTPServer(("0.0.0.0", args.port), _HttpHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"HTTP server listening on port {args.port}")
    print("  GET  /state  → current page")
    print("  POST /action → button press from app")
    print("Terminal input also accepted (type as before). Ctrl-C to quit.\n")

    def _terminal_input_loop():
        """Forward terminal keystrokes into the same action queue as HTTP actions."""
        while True:
            try:
                line = input("You: ").strip()
            except EOFError:
                break
            if line.lower() in ("quit", "exit"):
                print("\nRobot: Goodbye!")
                import os as _os
                _os.kill(_os.getpid(), 2)  # SIGINT → triggers KeyboardInterrupt in main
                break
            if line:
                _action_queue.put(line)

    input_thread = threading.Thread(target=_terminal_input_loop, daemon=True)
    input_thread.start()

    robot = HealthRobotGraph()
    try:
        robot.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\nShutting down HTTP server.")
        server.shutdown()


if __name__ == "__main__":
    main()
