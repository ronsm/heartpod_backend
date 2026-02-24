# HeartPod Backend

A LangGraph-based health screening application for the **Temi** robot. Temi guides a patient through a lifestyle questionnaire and three device readings (oximeter, blood pressure, scale), then displays a summary of their results.

## File Structure

```
heartpod_backend/
├── main.py           ← Entry point: python main.py
├── config.py         ← All static strings and constants (edit messages here)
├── state.py          ← ConversationState TypedDict
├── ws_server.py      ← WebSocket server: pushes state to the app, receives actions
├── robot.py          ← HealthRobotGraph – nodes, graph wiring, run loop
├── device.py         ← device_queue and simulate_reading() (swap for real hardware)
├── llm_helpers.py    ← LLMHelper class – all LLM prompts live here
├── listen.py         ← Speech-to-text subprocess (Whisper + SpeechRecognition)
├── print_utility.py  ← PrintUtility – thermal receipt printer (Epson USB)
└── sensors/
    ├── sensor_oximeter.py        ← Heart rate / SpO2 via BLE
    ├── sensor_blood_pressure.py  ← Blood pressure via BLE
    └── sensor_scales.py          ← Weight via BLE
```

## State Flow

| State | Page | Description |
|-------|------|-------------|
| idle | 01 | Welcome – yes/no to begin |
| welcome | 02 | Consent and comfort instructions |
| q1 | 03 | Lifestyle question: smoking frequency |
| q2 | 04 | Lifestyle question: exercise frequency |
| q3 | 05 | Lifestyle question: alcohol units/week |
| measure_intro | 06 | Overview of the three measurements |
| oximeter_intro | 07 | Oximeter placement instructions |
| oximeter_reading | 08 | Reads heart rate and SpO2 from device |
| oximeter_done | 09 | Shows HR + SpO2 result |
| bp_intro | 10 | Blood pressure cuff instructions |
| bp_reading | 11 | Reads blood pressure from device |
| bp_done | 12 | Shows BP result |
| scale_intro | 13 | Scale instructions |
| scale_reading | 14 | Reads weight from device |
| scale_done | 15 | Shows weight result |
| recap | 16 | Full summary of answers and readings |
| sorry | 17 | Device timeout – offers retry |

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set your OpenAI API key:**
   ```bash
   export OPENAI_API_KEY='your-api-key-here'
   ```

## Running

```bash
python main.py [OPTIONS]
```

### Command-line flags

| Flag | Description |
|------|-------------|
| `--dummy` | Use simulated sensor data instead of real BLE hardware |
| `--no-printer` | Disable the thermal receipt printer |
| `--no-listen` | Disable the speech-to-text listener |
| `--port PORT` | Port for the WebSocket server (default: 8000) |

**Examples:**

```bash
# Full production run (real sensors + printer)
python main.py

# Development / demo run (simulated sensors, no printer, no mic)
python main.py --dummy --no-printer --no-listen

# Real sensors, no printer, custom port
python main.py --no-printer --port 8080
```

## Communication Protocol

The backend runs a WebSocket server (default port 8000). The Android app connects to `ws://<host>:8000`.

**Backend → app** (state push, sent on every page transition and on connect):
```json
{"type": "state", "page_id": 1, "data": {"message": "...", ...}}
```

**App → backend** (button/action events):
```json
{"type": "action", "action": "start", "data": {}}
```

## Speech-to-Text (`listen.py`)

`listen.py` runs as a subprocess and connects to the same WebSocket server, sending recognised speech as `action=answer` messages. It can also be run standalone for microphone testing:

```bash
# List available microphones
python listen.py --list-microphones

# Use a specific microphone with a fixed energy threshold
python listen.py --microphone 2 --energy-threshold 300
```

## Key Design Decisions

- **All dialogue strings live in `config.py`** (`PAGE_CONFIG`). Edit messages there – do not hardcode strings elsewhere.
- **Questionnaire questions (Q1/Q2/Q3)** re-prompt inline on invalid input; they never trigger the sorry page. Any question can be skipped (recorded as `"skipped"`).
- **The sorry page is triggered by device timeouts only**, not by user confusion or invalid input. Off-topic questions at any state are handled gracefully by `LLMHelper.handle_general_question()`, which answers then re-prompts within the same state.
- **Device readings** block on a queue (`device_queue.get(timeout=30)`). For demo purposes, `simulate_reading()` in `device.py` auto-fires a fake reading. Remove that call in `robot.py` when connecting real hardware.

## Configuration (`config.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `READING_TIMEOUT` | 30s | Seconds before a device reading times out |
| `MAX_RETRIES` | 3 | Consecutive sorry-retries before returning to idle |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model used for intent detection |
| `LLM_TEMPERATURE` | 0.7 | LLM temperature |
