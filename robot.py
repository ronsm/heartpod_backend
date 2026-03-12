"""
HealthRobotGraph – LangGraph state machine and interactive run loop.

Nodes map 1-to-1 with the states in the state machine diagram.
The run() method drives the conversation; all routing logic lives here.
"""

import json
import queue as queue_module

from langgraph.graph import StateGraph, END

import time

from config import PAGE_CONFIG, MAX_RETRIES, READING_TIMEOUT, RECAP_RETURN_DELAY
from state import ConversationState
from device import device_queue, simulate_reading, get_real_reading
from llm_helpers import LLMHelper
import stt
import tts
from ws_server import action_queue, reset_event, update_state, flush_action_queue, navigation_complete_event


class _ResetRequested(Exception):
    """Raised when the user taps the Reset button; unwinds to the run() loop."""


class HealthRobotGraph:

    def __init__(self, sensor_mode: str = "real", use_printer: bool = True):
        self.sensor_mode = sensor_mode
        self.llm = LLMHelper()
        self.graph = self._build_graph()
        self.printer = None
        if use_printer:
            try:
                from print_utility import PrintUtility
                self.printer = PrintUtility()
                print("  [Printer: ready]")
            except Exception as e:
                print(f"  [Printer: unavailable — {e}]")

    # ------------------------------------------------------------------
    # Node functions
    # Each node sets current_stage, page_id, and robot_response on state.
    # Nodes whose message depends on runtime data build the message inline;
    # all others pull directly from PAGE_CONFIG.
    # ------------------------------------------------------------------

    def _set_page(
        self, state: ConversationState, stage: str, message: str
    ) -> ConversationState:
        state["current_stage"] = stage
        state["page_id"] = PAGE_CONFIG[stage]["page_id"]
        state["robot_response"] = message
        update_state(int(state["page_id"]), self._build_data(state))
        flush_action_queue()
        return state

    def _build_data(self, state: ConversationState) -> dict:
        """Build the data payload for the current stage to send via WebSocket state message."""
        stage = state["current_stage"]
        r = state.get("readings", {})

        if stage == "idle":
            data = {}
        elif stage == "welcome":
            data = {"message": state["robot_response"]}
        elif stage in ("q1", "q2", "q3"):
            cfg = PAGE_CONFIG[stage]
            question = cfg["message"].split("\n")[0]
            data = {"question": question, "options": json.dumps(cfg["options"])}
        elif stage == "measure_intro":
            data = {"message": state["robot_response"]}
        elif stage == "oximeter_intro":
            data = {"device": "oximeter", "video_id": PAGE_CONFIG["oximeter_intro"]["video_id"]}
        elif stage == "oximeter_reading":
            data = {"message": state["robot_response"]}
        elif stage == "oximeter_done":
            data = {
                "value": f"HR: {r.get('oximeter_hr', '?')} bpm  /  SpO2: {r.get('oximeter_spo2', '?')}%",
                "unit": "",
            }
        elif stage == "bp_intro":
            data = {"device": "blood pressure monitor", "video_id": PAGE_CONFIG["bp_intro"]["video_id"]}
        elif stage == "bp_reading":
            data = {"message": state["robot_response"]}
        elif stage == "bp_done":
            data = {"value": r.get("bp", "?"), "unit": "mmHg"}
        elif stage == "scale_intro":
            data = {"device": "scale", "video_id": PAGE_CONFIG["scale_intro"]["video_id"]}
        elif stage == "scale_reading":
            data = {"message": state["robot_response"]}
        elif stage == "scale_done":
            data = {"value": str(r.get("scale", "?")), "unit": "kg"}
        elif stage == "recap":
            a = state["answers"]
            data = {
                "q1": a.get("q1", "not answered"),
                "q2": a.get("q2", "not answered"),
                "q3": a.get("q3", "not answered"),
                "oximeter": f"{r.get('oximeter_hr', '?')} bpm / {r.get('oximeter_spo2', '?')}%",
                "bp": f"{r.get('bp', '?')} mmHg",
                "weight": f"{r.get('scale', '?')} kg",
            }
        elif stage == "sorry":
            data = {"message": state["robot_response"]}
        else:
            data = {}

        # Attach optional Temi navigation target — set "location" in PAGE_CONFIG to use.
        location = PAGE_CONFIG.get(stage, {}).get("location", "")
        if location:
            data["location"] = location

        return data

    def _simple_node(self, stage: str):
        """Factory: returns a node function that just displays PAGE_CONFIG text."""

        def node(state: ConversationState) -> ConversationState:
            cfg = PAGE_CONFIG[stage]
            return self._set_page(state, stage, cfg.get("speech", cfg["message"]))

        node.__name__ = f"{stage}_node"
        return node

    # Simple nodes wired up via the factory
    idle_node = property(lambda self: self._simple_node("idle"))
    welcome_node = property(lambda self: self._simple_node("welcome"))
    q1_node = property(lambda self: self._simple_node("q1"))
    q2_node = property(lambda self: self._simple_node("q2"))
    q3_node = property(lambda self: self._simple_node("q3"))
    measure_intro_node = property(lambda self: self._simple_node("measure_intro"))
    oximeter_intro_node = property(lambda self: self._simple_node("oximeter_intro"))
    oximeter_reading_node = property(lambda self: self._simple_node("oximeter_reading"))
    bp_intro_node = property(lambda self: self._simple_node("bp_intro"))
    bp_reading_node = property(lambda self: self._simple_node("bp_reading"))
    scale_intro_node = property(lambda self: self._simple_node("scale_intro"))
    scale_reading_node = property(lambda self: self._simple_node("scale_reading"))

    # Nodes that embed live readings in their message
    def oximeter_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        reading = (
            f"Your heart rate is {r.get('oximeter_hr', '?')} beats per minute, "
            f"and your blood oxygen level is {r.get('oximeter_spo2', '?')} percent. "
        )
        msg = reading + PAGE_CONFIG["oximeter_done"]["message"]
        return self._set_page(state, "oximeter_done", msg)

    def bp_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        bp = r.get("bp", "?/?")
        try:
            systolic, diastolic = str(bp).split("/")
            reading = f"Your blood pressure is {systolic.strip()} over {diastolic.strip()}. "
        except ValueError:
            reading = f"Your blood pressure is {bp}. "
        msg = reading + PAGE_CONFIG["bp_done"]["message"]
        return self._set_page(state, "bp_done", msg)

    def scale_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        reading = f"Your weight is {r.get('scale', '?')} kilograms. "
        msg = reading + PAGE_CONFIG["scale_done"]["message"]
        return self._set_page(state, "scale_done", msg)

    def recap_node(self, state: ConversationState) -> ConversationState:
        return self._set_page(state, "recap", PAGE_CONFIG["recap"]["message"])

    def sorry_node(self, state: ConversationState) -> ConversationState:
        """Triggered only by a device reading failure (timeout)."""
        return self._set_page(state, "sorry", PAGE_CONFIG["sorry"]["message"])

    # ------------------------------------------------------------------
    # LangGraph wiring
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(ConversationState)

        # Register all nodes
        for stage in (
            "idle",
            "welcome",
            "q1",
            "q2",
            "q3",
            "measure_intro",
            "oximeter_intro",
            "oximeter_reading",
            "oximeter_done",
            "bp_intro",
            "bp_reading",
            "bp_done",
            "scale_intro",
            "scale_reading",
            "scale_done",
            "recap",
            "sorry",
        ):
            node_fn = getattr(self, f"{stage}_node", None) or self._simple_node(stage)
            workflow.add_node(stage, node_fn)

        workflow.set_entry_point("idle")

        # Linear edges (branching is handled in run())
        for src, dst in [
            ("idle", "welcome"),
            ("welcome", "q1"),
            ("q1", "q2"),
            ("q2", "q3"),
            ("q3", "measure_intro"),
            ("measure_intro", "oximeter_intro"),
            ("oximeter_intro", "oximeter_reading"),
            ("oximeter_reading", "oximeter_done"),
            ("oximeter_done", "bp_intro"),
            ("bp_intro", "bp_reading"),
            ("bp_reading", "bp_done"),
            ("bp_done", "scale_intro"),
            ("scale_intro", "scale_reading"),
            ("scale_reading", "scale_done"),
            ("scale_done", "recap"),
            ("recap", END),
            ("sorry", END),
        ]:
            workflow.add_edge(src, dst)

        return workflow.compile()

    # ------------------------------------------------------------------
    # Interactive run loop helpers
    # ------------------------------------------------------------------

    def _print_robot(self, msg: str, page_id: str = None):
        prefix = f"[Page {page_id}] " if page_id else ""
        print(f"\n{prefix}Robot: {msg}\n")
        tts.speak(msg)

    def _ask_user(self) -> str:
        """Block until the Android app (or terminal) posts an action.
        Raises _ResetRequested immediately if the reset button has been pressed."""
        while True:
            if reset_event.is_set():
                raise _ResetRequested()
            try:
                result = action_queue.get(timeout=0.2)
            except queue_module.Empty:
                continue
            tts.stop()  # cut speech the moment the user acts
            if reset_event.is_set():
                raise _ResetRequested()
            return result

    def _wait_for_consent(self, action_context: str, robot_message: str = "") -> bool:
        """Like _wait_for_proceed but returns False if the user declines."""
        while True:
            user_input = self._ask_user()
            should_go, message = self.llm.evaluate_proceed(user_input, action_context, robot_message)
            if should_go:
                return True
            self._print_robot(message)
            return False

    def _wait_for_proceed(self, action_context: str, robot_message: str = ""):
        """Block until the user confirms they are ready. Handles diversions via LLM."""
        while True:
            user_input = self._ask_user()
            should_go, message = self.llm.evaluate_proceed(user_input, action_context, robot_message)
            if should_go:
                return
            self._print_robot(message)

    def _confirm_reading(self, action_context: str, robot_message: str = "") -> bool:
        """
        Wait for the user to confirm a captured reading or request a redo.
        Returns True if confirmed, False if they want to retry the reading.
        """
        while True:
            user_input = self._ask_user()
            if user_input.lower() == "retry":
                return False
            should_go, message = self.llm.evaluate_proceed(user_input, action_context, robot_message)
            if should_go:
                return True
            self._print_robot(message)

    def _do_device_reading(self, device: str, state: ConversationState) -> bool:
        """
        Obtain a reading from `device` and store it in state["readings"].
        Returns True on success, False on failure/timeout.

        In real mode: calls the BLE sensor directly via get_real_reading().
        In dummy mode: fires a simulated reading onto device_queue.
        """
        if self.sensor_mode == "real":
            print(f"  [Waiting for {device} data (real hardware)...]")
            data = get_real_reading(device)
            if data is None:
                print(f"  [No reading received from {device}]")
                return False
        else:
            print(f"  [Waiting for {device} data (dummy, timeout={READING_TIMEOUT}s)...]")
            simulate_reading(device, delay=2.0)
            try:
                data = device_queue.get(timeout=READING_TIMEOUT)
            except queue_module.Empty:
                print(f"  [Timeout: no data received from {device}]")
                return False

        print(f"  [Data received: {data}]")
        if device == "oximeter":
            state["readings"]["oximeter_hr"] = data["value"]["hr"]
            state["readings"]["oximeter_spo2"] = data["value"]["spo2"]
        elif device == "bp":
            state["readings"]["bp"] = data["value"]
        elif device == "scale":
            state["readings"]["scale"] = data["value"]
        return True

    def _reading_loop(
        self, device: str, intro_stage: str, done_stage: str, state: ConversationState
    ) -> bool:
        """
        Run the full intro → reading → done cycle for one device.
        Returns True if the reading succeeded, False if the user gave up or
        retries were exhausted (session continues with the next sensor).
        """
        intro_node = getattr(self, f"{intro_stage}_node")
        done_node = getattr(self, f"{done_stage}_node")

        state = intro_node(state)
        self._print_robot(state["robot_response"], state["page_id"])
        stt.hold()
        self._wait_for_proceed(PAGE_CONFIG[intro_stage]["action_context"], state["robot_response"])
        stt.release_hold()

        while True:
            reading_node = getattr(self, f"{device}_reading_node")
            state = reading_node(state)
            self._print_robot(state["robot_response"], state["page_id"])

            if self._do_device_reading(device, state):
                state = done_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                if self._confirm_reading(PAGE_CONFIG[done_stage]["action_context"], state["robot_response"]):
                    return True
                continue  # user pressed Retry — redo the reading

            # Device timeout → sorry
            state["retry_count"] += 1
            state["retry_stage"] = f"{device}_reading"
            state = self.sorry_node(state)

            if state["retry_count"] >= MAX_RETRIES:
                self._print_robot(
                    state["robot_response"] + " Maximum retries reached. We will skip this measurement and move on.",
                    state["page_id"],
                )
                return False

            self._print_robot(state["robot_response"], state["page_id"])

            user_input = self._ask_user()
            if not self.llm.retry_or_give_up(user_input):
                self._print_robot("No problem. We will skip this measurement and move on.")
                return False

    def _print_receipt(self, state: ConversationState):
        """Print header, results, and footer to the thermal printer if available."""
        if self.printer is None:
            return
        r = state["readings"]
        bp = r.get("bp", "?/?")
        try:
            systolic, diastolic = str(bp).split("/")
            systolic, diastolic = int(systolic.strip()), int(diastolic.strip())
        except (ValueError, AttributeError):
            systolic, diastolic = "?", "?"
        results = {
            "spo2": r.get("oximeter_spo2", "?"),
            "heart_rate": r.get("oximeter_hr", "?"),
            "weight": r.get("scale", "?"),
            "height": "\u2014",  # not captured in this workflow
            "systolic": systolic,
            "diastolic": diastolic,
        }
        try:
            self.printer.print_header()
            self.printer.print_results(results)
            self.printer.print_footer()
        except Exception as e:
            print(f"  [Printer error: {e}]")

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 60)
        print("HeartPod")
        print("=" * 60)
        print("(Type 'quit' or 'exit' to end)\n")

        while True:  # outer loop: returns here after recap, giving up, or reset
            reset_event.clear()
            flush_action_queue()
            stt.release_hold()  # clear any stale hold from a reset during a video page
            try:
                state: ConversationState = {
                    "current_stage": "idle",
                    "page_id": PAGE_CONFIG["idle"]["page_id"],
                    "robot_response": "",
                    "answers": {},
                    "readings": {},
                    "retry_stage": "",
                    "retry_count": 0,
                }

                # ── idle ──────────────────────────────────────────────────
                state = self.idle_node(state)
                # Idle page is tap-only: stop STT so no ambient speech
                # is captured while Temi navigates to the front door.
                stt.stop()
                # In temi mode, wait for Temi to arrive at the front door
                # before speaking so the greeting plays on arrival, not in transit.
                if tts.mode() == "temi":
                    navigation_complete_event.clear()
                    while not navigation_complete_event.wait(timeout=0.5):
                        if reset_event.is_set():
                            raise _ResetRequested()
                # Discard any speech items captured before the lock took effect.
                flush_action_queue()
                self._print_robot(state["robot_response"], state["page_id"])
                self._wait_for_proceed(PAGE_CONFIG["idle"]["action_context"], state["robot_response"])
                stt.start()

                # ── welcome ───────────────────────────────────────────────
                state = self.welcome_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                if not self._wait_for_consent(PAGE_CONFIG["welcome"]["action_context"], state["robot_response"]):
                    self._print_robot("No problem. Feel free to come back any time.")
                    continue

                # ── questionnaire ─────────────────────────────────────────
                for qkey in ("q1", "q2", "q3"):
                    q_node = getattr(self, f"{qkey}_node")
                    state = q_node(state)
                    self._print_robot(state["robot_response"], state["page_id"])
                    while True:
                        user_input = self._ask_user()
                        intent, value = self.llm.evaluate_questionnaire_input(
                            user_input, qkey, PAGE_CONFIG[qkey]["message"]
                        )
                        if intent == "skip":
                            state["answers"][qkey] = "skipped"
                            print(f"  [Question {qkey} skipped]")
                            break
                        if intent == "answer":
                            state["answers"][qkey] = value
                            print(f"  [Recorded {qkey}: {value}]")
                            break
                        opts = "\n    ".join(PAGE_CONFIG[qkey]["options"])
                        self._print_robot(
                            f"I didn't quite catch that. Please choose one of:\n    {opts}"
                        )

                # ── measure intro ─────────────────────────────────────────
                state = self.measure_intro_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                self._wait_for_proceed(PAGE_CONFIG["measure_intro"]["action_context"], state["robot_response"])

                # ── device readings ───────────────────────────────────────
                self._reading_loop("oximeter", "oximeter_intro", "oximeter_done", state)
                self._reading_loop("bp", "bp_intro", "bp_done", state)
                self._reading_loop("scale", "scale_intro", "scale_done", state)

                # ── recap ─────────────────────────────────────────────────
                state = self.recap_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                self._print_receipt(state)
                time.sleep(RECAP_RETURN_DELAY)

            except _ResetRequested:
                print("\n  [Reset requested — restarting]\n")
