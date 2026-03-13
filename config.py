# ---------------------------------------------------------------------------
# Runtime constants
# ---------------------------------------------------------------------------

# Application-level retry limit: how many times the user can ask to redo
# a failed device reading before the session returns to idle.
# (Distinct from per-sensor BLE connection attempts, which live in each sensor module.)
MAX_RETRIES = 3

# How long (seconds) to stay on the recap page before automatically returning to idle.
RECAP_RETURN_DELAY = 30

# Timeout used in dummy/simulated mode when waiting for a fake device reading.
READING_TIMEOUT = 30  # seconds

# LLM settings — temperature 0.0 gives deterministic, consistent classifications.
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0.5

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
            "You can talk me at any point as if you are talking to a human. Just know that I won't be listening while I am talking."
            "Tap 'Start Screening' on my screen to begin."
        ),
        "action_context": (
            "confirming whether they want to begin the health check "
            "(yes to start, no to decline)"
        ),
        "location": "front door",
        # "location": "triage",
    },
    "welcome": {
        "page_id": "02",
        "message": (
            "I'm HeartPod, your digital health assistant. I'll guide you step-by-step "
            "through the self-screening process and provide you with a copy of your "
            "results to take away.\n\nBefore we start, please take a seat and make "
            "yourself comfortable. If you are wearing a jacket or coat, you can "
            "remove it now, as it will make the process easier.\n\nI will ask a few "
            "general lifestyle questions to give the clinical team some background. "
            "You can choose to skip any question, if you wish.\n\n"
            "Throughout the session, you can interact by speaking to me or by tapping the touchscreen — whichever you prefer.\n\n"
            "Let me know if you wish to continue."
        ),
        "action_context": "confirming they consent to start the session",
        "location": "triage",
    },
    "q1": {
        "page_id": "03",
        "message": (
            "Q1. Do you currently smoke?\n"
            "  1. Yes\n"
            "  2. No\n"
            "  3. Used to smoke"
        ),
        "options": [
            "Yes, I smoke",
            "No, I do not smoke",
            "I used to smoke",
        ],
        "speech": "Do you currently smoke? You can say your answer, tap it on screen, or say skip to move on.",
        "action_context": "answering a question about whether they smoke, or used to smoke",
    },
    "q2": {
        "page_id": "04",
        "message": (
            "Q2. What  physical activity do you commonnly engage with? This includes sports, housework, and gardening\n"
            "1. Light exercise, like walking, yoga, or light housework\n"
            "2. Moderate exercise, like aerobics, dancing, or hiking\n"
            "3. Vigorous exercise like rugby, gym, or climbing"
        ),
        "options": [
            "Light exercise, like walking, yoga, or light housework.",
            "Moderate exercise, like aerobics, dancing, or hiking.",
            "Vigorous exercise, like rugby, gym, or climbing.",
        ],
        "speech": "What  physical activity do you commonnly engage with? This includes sports, housework, and gardening. You can say your answer, tap it on screen, or say skip to move on.",
        "action_context": "answering a question about their level of physical activity",
    },
    "q3": {
        "page_id": "05",
        "message": (
            "Q3. How often do you do this activity in an average week?\n"
            "  1. Less than 1 hour per week\n"
            "  2. 1 - 3 hours per week\n"
            "  3. Over 3 hours per week"
        ),
        "options": [
            "Less than 1 hour per week.",
            "1 - 3 hours per week.",
            "Over 3 hours per week.",
        ],
        "speech": "How often do you do this activity in an average week? You can say your answer, tap it on screen, or say skip to move on.",
        "action_context": "answering a question about the frequency of their physical activity",
    },
    "measure_intro": {
        "page_id": "06",
        "message": (
            "Great, thank you for answering those questions! "
            "Now we'll take four measurements: an oximeter reading, "
            "a blood pressure reading, your weight, and your height. "
            "Just say 'continue' or press the button when you're happy to begin."
        ),
        "action_context": "confirming they are ready to start the measurements",
    },
    "oximeter_intro": {
        "page_id": "07",
        "message": "",
        "action_context": "confirming the oximeter is clipped onto their finger",
        "video_id": "oximeter",
    },
    "oximeter_reading": {
        "page_id": "08",
        "message": "Taking oximeter reading... Please stay still.",
        "action_context": "waiting for oximeter device data",
    },
    "oximeter_done": {
        "page_id": "09",
        "message": (
            "Great. Thank you! I've recorded your blood oxygen and heart rate "
            "information. You can now unclip it from your finger and place it back on the table. Next, we will measure your blood pressure. "
            "Say 'continue' or press the button when you're ready for the next measurement."
        ),
        "action_context": "confirming they are ready to continue to blood pressure",
    },
    "bp_intro": {
        "page_id": "10",
        "message": "",
        "action_context": "confirming the blood pressure cuff is on and they are ready",
        "video_id": "bpm",
    },
    "bp_reading": {
        "page_id": "11",
        "message": "Measuring now. Please relax and stay still.",
        "action_context": "waiting for blood pressure device data",
    },
    "bp_done": {
        "page_id": "12",
        "message": (
            "Great. Thank you! I've recorded your blood pressure. You can now remove it from your armm and place it back on the table."
            "Next, we will measure your weight. "
            "Say 'continue' or press the button when you're ready."
        ),
        "action_context": "confirming they are ready to continue to the scale",
    },
    "scale_intro": {
        "page_id": "13",
        "message": "",
        "action_context": "confirming they are standing on the scale",
        "video_id": "scales",
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
            "Say 'continue' or press the button when you're ready for the height measurement."
        ),
        "action_context": "confirming they are ready to continue to the height measurement",
    },
    "height_intro": {
        "page_id": "18",
        "message": "",
        "action_context": "confirming they are standing in position for the height reading",
        "video_id": "height",
    },
    "height_reading": {
        "page_id": "19",
        "message": "Taking height reading... please stand still.",
        "action_context": "waiting for height sensor data",
    },
    "height_done": {
        "page_id": "20",
        "message": (
            "Great. Thank you! I've recorded your height. "
            "Say 'continue' or press the button to see your summary."
        ),
        "action_context": "confirming they are ready to see the recap",
    },
    "recap": {
        "page_id": "16",
        "message": (
            "We have now completed all the measurements. Your results are shown "
            "on my screen. I have printed a paper copy for you to take away."
        ),
        "action_context": "reviewing their health check summary",
    },
    "sorry": {
        "page_id": "17",
        "message": "Sorry, we weren't able to get a reading. Would you like to try again?",
        "action_context": "deciding whether to retry the failed device reading",
    },
}
