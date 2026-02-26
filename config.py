# ---------------------------------------------------------------------------
# Runtime constants
# ---------------------------------------------------------------------------

# Application-level retry limit: how many times the user can ask to redo
# a failed device reading before the session returns to idle.
# (Distinct from per-sensor BLE connection attempts, which live in each sensor module.)
MAX_RETRIES = 3

# Timeout used in dummy/simulated mode when waiting for a fake device reading.
READING_TIMEOUT = 30  # seconds

# LLM settings — temperature 0.0 gives deterministic, consistent classifications.
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0.0

# How long to wait after TTS finishes before reopening the ASR pipeline.
# Increase if the ASR still occasionally hears the tail end of the robot's voice.
ASR_UNMUTE_DELAY = 1.0  # seconds

# ---------------------------------------------------------------------------
# PAGE_CONFIG – single source of all static strings
#
# Each key is a state/node name. Every entry must have:
#   page_id        – UI page identifier shown on screen
#   message        – text the robot speaks when entering this state
#   action_context – short description passed to the LLM so it knows what
#                    the user was asked to do at this point
#
# Question states (q1/q2/q3) additionally have:
#   options        – ordered list of valid answer strings
# ---------------------------------------------------------------------------
PAGE_CONFIG = {
    "idle": {
        "page_id": "01",
        "message": (
            "Hello, welcome to the self-screening health check pod. "
            "If you would like to start a self-screening, please choose "
            "'Start Self-Screening' on my screen."
        ),
        "action_context": (
            "confirming whether they want to begin the health check "
            "(yes to start, no to decline)"
        ),
    },
    "welcome": {
        "page_id": "02",
        "message": (
            "I'm Temi, your digital health assistant. I'll guide you step-by-step "
            "through the self-screening process and provide you with a copy of your "
            "results to take away. Before we start, please take a seat and make "
            "yourself comfortable. If you are wearing a jacket or coat, you can "
            "remove it now - it will make the process easier. I will ask a few "
            "general lifestyle questions to give the clinical team some background. "
            "You can choose to skip any question, if you wish. "
            "Let me know if you wish to continue."
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
            "Now we'll take three quick measurements: an oximeter reading, "
            "a blood pressure reading, and your weight. "
            "Just say 'continue' when you're happy to begin."
        ),
        "action_context": "confirming they are ready to start the measurements",
    },
    "oximeter_intro": {
        "page_id": "07",
        "message": (
            "Remain seated, and breathe comfortably. Now, place your index finger "
            "inside the oximeter, with your fingernail facing upwards towards the "
            "ceiling. Keep your hand resting on the table. "
            "Say 'ready' when it's in place."
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
        "message": (
            "Great. Thank you! I've recorded your blood oxygen and heart rate "
            "information. Next, we will measure your blood pressure. "
            "Say 'continue' when you're ready for the next measurement."
        ),
        "action_context": "confirming they are ready to continue to blood pressure",
    },
    "bp_intro": {
        "page_id": "10",
        "message": (
            "Next, we'll measure your blood pressure. Please put on the blood "
            "pressure cuff and sit comfortably with your arm resting at heart level. "
            "Say 'ready' when set."
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
        "message": (
            "Great. Thank you! I've recorded your blood pressure. "
            "Next, we will measure your weight. "
            "Say 'continue' when you're ready for the final measurement."
        ),
        "action_context": "confirming they are ready to continue to the scale",
    },
    "scale_intro": {
        "page_id": "13",
        "message": (
            "Finally, we'll measure your weight. Please step onto the scale, "
            "which is over here on your [left/right]. Once you are on the scale, "
            "stand straight and as still as possible. "
            "Say 'ready' when you're on the scale."
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
        "message": (
            "Great. Thank you! I've recorded your weight. "
            "You can now step off the scale and sit back down. "
            "Say 'continue' to see your summary."
        ),
        "action_context": "confirming they are ready to see the recap",
    },
    "recap": {
        "page_id": "16",
        "message": (
            "We have now completed all the measurements. Your results are shown "
            "on my screen. Please wait a moment while I also print you a paper "
            "copy to take away."
        ),
        "action_context": "reviewing their health check summary",
    },
    "sorry": {
        "page_id": "17",
        "message": "Sorry, we weren't able to get a reading. Would you like to try again?",
        "action_context": "deciding whether to retry the failed device reading",
    },
}
