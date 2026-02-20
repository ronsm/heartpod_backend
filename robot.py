"""
HealthRobotGraph – LangGraph state machine and interactive run loop.

Nodes map 1-to-1 with the states in the state machine diagram.
The run() method drives the conversation; all routing logic lives here.
"""

import queue as queue_module

from langgraph.graph import StateGraph, END

from config import PAGE_CONFIG, MAX_RETRIES, READING_TIMEOUT
from state import ConversationState
from device import device_queue, simulate_reading, get_real_reading
from llm_helpers import LLMHelper


class HealthRobotGraph:

    def __init__(self, sensor_mode: str = "real"):
        self.sensor_mode = sensor_mode
        self.llm = LLMHelper()
        self.graph = self._build_graph()

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
        return state

    def _simple_node(self, stage: str):
        """Factory: returns a node function that just displays PAGE_CONFIG text."""

        def node(state: ConversationState) -> ConversationState:
            return self._set_page(state, stage, PAGE_CONFIG[stage]["message"])

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
        msg = (
            f"{PAGE_CONFIG['oximeter_done']['message']}\n"
            f"  Heart Rate: {r.get('oximeter_hr', '?')} bpm\n"
            f"  SpO2:       {r.get('oximeter_spo2', '?')}%"
        )
        return self._set_page(state, "oximeter_done", msg)

    def bp_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        msg = (
            f"{PAGE_CONFIG['bp_done']['message']}\n"
            f"  Blood Pressure: {r.get('bp', '?')} mmHg"
        )
        return self._set_page(state, "bp_done", msg)

    def scale_done_node(self, state: ConversationState) -> ConversationState:
        r = state["readings"]
        msg = (
            f"{PAGE_CONFIG['scale_done']['message']}\n"
            f"  Weight: {r.get('scale', '?')} kg"
        )
        return self._set_page(state, "scale_done", msg)

    def recap_node(self, state: ConversationState) -> ConversationState:
        a = state["answers"]
        r = state["readings"]
        lines = [
            PAGE_CONFIG["recap"]["message"],
            "",
            "Questionnaire answers:",
            f"  Smoking:   {a.get('q1', 'not answered')}",
            f"  Exercise:  {a.get('q2', 'not answered')}",
            f"  Alcohol:   {a.get('q3', 'not answered')}",
            "",
            "Measurements:",
            f"  Heart Rate: {r.get('oximeter_hr', '?')} bpm",
            f"  SpO2:       {r.get('oximeter_spo2', '?')}%",
            f"  BP:         {r.get('bp', '?')} mmHg",
            f"  Weight:     {r.get('scale', '?')} kg",
            "",
            "Thank you for completing your health check! Say anything to return to the start.",
        ]
        return self._set_page(state, "recap", "\n".join(lines))

    def sorry_node(self, state: ConversationState) -> ConversationState:
        """Triggered only by a device reading failure (timeout)."""
        msg = (
            f"{PAGE_CONFIG['sorry']['message_device']}\n"
            f"(Retry {state.get('retry_count', 0)}/{MAX_RETRIES})"
        )
        return self._set_page(state, "sorry", msg)

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

    def _ask_user(self) -> str:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("quit", "exit"):
                print("\nRobot: Goodbye! Come back anytime.")
                raise SystemExit(0)
            if user_input:
                return user_input

    def _wait_for_proceed(self, action_context: str):
        """Block until the user confirms they are ready. Handles diversions via LLM."""
        while True:
            user_input = self._ask_user()
            if self.llm.should_proceed(user_input, action_context):
                return
            response = self.llm.handle_general_question(user_input, action_context)
            self._print_robot(response)

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
        retries were exhausted (caller should `continue` back to idle).
        """
        intro_node = getattr(self, f"{intro_stage}_node")
        done_node = getattr(self, f"{done_stage}_node")

        state = intro_node(state)
        self._print_robot(state["robot_response"], state["page_id"])
        self._wait_for_proceed(PAGE_CONFIG[intro_stage]["action_context"])

        while True:
            reading_node = getattr(self, f"{device}_reading_node")
            state = reading_node(state)
            self._print_robot(state["robot_response"], state["page_id"])

            if self._do_device_reading(device, state):
                state = done_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                self._wait_for_proceed(PAGE_CONFIG[done_stage]["action_context"])
                return True

            # Device timeout → sorry
            state["retry_count"] += 1
            state["retry_stage"] = f"{device}_reading"
            state = self.sorry_node(state)
            self._print_robot(state["robot_response"], state["page_id"])

            if state["retry_count"] >= MAX_RETRIES:
                self._print_robot("Maximum retries reached. Returning to start.")
                return False

            user_input = self._ask_user()
            if not self.llm.retry_or_give_up(user_input):
                self._print_robot("No problem. Returning to start.")
                return False

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 60)
        print("HeartPod")
        print("=" * 60)
        print("(Type 'quit' or 'exit' to end)\n")

        while True:  # outer loop: returns here after recap or giving up
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

            # ── questionnaire ─────────────────────────────────────────
            for qkey in ("q1", "q2", "q3"):
                q_node = getattr(self, f"{qkey}_node")
                state = q_node(state)
                self._print_robot(state["robot_response"], state["page_id"])
                while True:
                    user_input = self._ask_user()
                    if self.llm.user_wants_to_skip(user_input):
                        state["answers"][qkey] = "skipped"
                        print(f"  [Question {qkey} skipped]")
                        break
                    matched = self.llm.validate_answer(user_input, qkey)
                    if matched:
                        state["answers"][qkey] = matched
                        print(f"  [Recorded {qkey}: {matched}]")
                        break
                    opts = "\n".join(
                        f"  {i+1}. {o}"
                        for i, o in enumerate(PAGE_CONFIG[qkey]["options"])
                    )
                    self._print_robot(
                        f"I didn't quite catch that. Please choose one of:\n{opts}"
                    )

            # ── measure intro ─────────────────────────────────────────
            state = self.measure_intro_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._wait_for_proceed(PAGE_CONFIG["measure_intro"]["action_context"])

            # ── device readings ───────────────────────────────────────
            if not self._reading_loop(
                "oximeter", "oximeter_intro", "oximeter_done", state
            ):
                continue
            if not self._reading_loop("bp", "bp_intro", "bp_done", state):
                continue
            if not self._reading_loop("scale", "scale_intro", "scale_done", state):
                continue

            # ── recap ─────────────────────────────────────────────────
            state = self.recap_node(state)
            self._print_robot(state["robot_response"], state["page_id"])
            self._ask_user()  # any input returns to idle
