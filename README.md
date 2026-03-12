# HeartPod Backend

A LangGraph-based health screening application for the **Temi** robot. Temi guides a patient through a lifestyle questionnaire and three device readings (oximeter, blood pressure, scale), then displays a summary of their results.

## File Structure

```
heartpod_backend/
├── main.py              ← Entry point: python main.py
├── config.py            ← All static strings and constants (edit messages here)
├── state.py             ← ConversationState TypedDict
├── stt.py               ← STT client: connects to stt_server.py, provides start()/stop()
├── stt_server.py        ← Standalone speech-to-text server (run separately)
├── stt_client.py        ← Demo client for stt_server.py (for testing)
├── ws_server.py         ← WebSocket server: pushes state to the app, receives actions
├── tts.py               ← Text-to-speech engine (none / local / temi mode)
├── robot.py             ← HealthRobotGraph – nodes, graph wiring, run loop
├── device.py            ← device_queue and simulate_reading() (swap for real hardware)
├── llm_helpers.py       ← LLMHelper class – all LLM prompts live here
├── print_utility.py     ← PrintUtility – thermal receipt printer (Epson USB)
├── download_voice.py    ← Downloads the Piper TTS alba voice model into ./voices/
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

3. **(Optional) Download the local TTS voice model** — required if using `--tts local`:
   ```bash
   python download_voice.py
   ```
   This downloads the Piper **alba** voice (~65 MB) into `./voices/`. Only needed once.

## Running

Speech-to-text runs as a separate server process. Start it first, then start the backend.

**Terminal 1 — STT server:**
```bash
python stt_server.py [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `-l`, `--list-microphones` | List available microphones and exit |
| `-m M`, `--microphone M` | Microphone device index (default: system default) |
| `-t N`, `--energy-threshold N` | Fixed energy threshold (default: auto-calibrate) |

**Terminal 2 — Backend:**
```bash
python main.py [OPTIONS]
```

### Command-line flags

| Flag | Description |
|------|-------------|
| `--dummy` | Use simulated sensor data instead of real BLE hardware |
| `--no-printer` | Disable the thermal receipt printer |
| `--no-listen` | Do not connect to the STT server |
| `--tts {none,local,temi}` | Text-to-speech mode (default: `none`) |
| `--port PORT` | Port for the WebSocket server (default: `8000`) |

**Examples:**

```bash
# Full production run (real sensors + printer, Temi TTS)
python main.py --tts temi

# Development / demo run (simulated sensors, local TTS)
python main.py --dummy --no-printer --tts local

# Real sensors, no printer, custom port, silent
python main.py --no-printer --port 8080

# No speech input (terminal and touchscreen only)
python main.py --no-listen --dummy --no-printer
```

## Text-to-Speech

The `--tts` flag selects the TTS mode:

| Mode | Description |
|------|-------------|
| `none` | Silent – no speech output (default) |
| `local` | Speaks through the backend machine's audio output using [Piper TTS](https://github.com/rhasspy/piper) with the **alba** voice (macOS: `afplay`; Linux: `aplay`) |
| `temi` | Sends `{"type": "tts", "text": "..."}` WebSocket messages to the Android app for the Temi robot to speak |

The text spoken is exactly what the robot prints to the terminal at each step of the conversation. Speech runs in a background thread and is interrupted immediately when the user acts or a new utterance starts.

In both `local` and `temi` modes, **the Android app's input buttons are locked for the duration of every TTS utterance** so the user cannot tap buttons while the robot is speaking.

### Setting up local TTS

`local` mode uses the `piper-tts` Python package with the **en_GB-alba-medium** voice. After installing dependencies, download the voice model (≈65 MB):

```bash
python download_voice.py
```

The model is saved to `./voices/` (gitignored). You only need to do this once.

## Speech-to-Text

Speech recognition runs as a standalone server (`stt_server.py`) that is separate from the backend. The backend connects to it as a client via `stt.py` and controls when recognition is active by sending `Start STT` / `Stop STT` commands over a TCP socket (port 61000, using Python's `multiprocessing.connection` protocol).

The STT server uses [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) (`small.en` model) for transcription and includes a hallucination filter. Ambient noise calibration runs once per client connection.

When the backend does not need voice input (during TTS playback, video playback, or on the tap-only idle page), it tells the server to stop listening. This avoids picking up the robot's own voice or video narration without any timers or mute state — the microphone simply is not recording.

### STT hold during video playback

Device instruction pages play an instructional video with narration. To prevent that narration from being recognised as user speech, `robot.py` calls `stt.hold()` before the video page and `stt.release_hold()` when the user leaves it. While a hold is active, `stt.start()` calls are suppressed. The hold is released either by the `video_ended` WebSocket message from the frontend (video finished naturally) or by `robot.py` when the user presses Ready.

## Communication Protocol

The backend runs a WebSocket server (default port 8000). The Android app connects to `ws://<host>:8000`.

**Backend → app** — state push, sent on every page transition and immediately on connect:
```json
{"type": "state", "page_id": 1, "data": {"message": "...", ...}}
```

**Backend → app** — TTS utterance (temi mode only), forwarded to the Temi robot to speak:
```json
{"type": "tts", "text": "Hello, welcome to the health check pod."}
```

**Backend → app** — TTS active flag (local mode), locks/unlocks input buttons on the display:
```json
{"type": "tts_active", "active": true}
{"type": "tts_active", "active": false}
```

**App → backend** — button/action events:
```json
{"type": "action", "action": "start", "data": {}}
```

**App → backend** — TTS status (temi mode only), sent by the app when Temi starts/stops speaking:
```json
{"type": "tts_status", "status": "start"}
{"type": "tts_status", "status": "stop"}
```

The `tts_status=stop` event tells the backend that the Temi has finished speaking, which triggers `stt.start()` so the microphone begins listening for user input. `tts_status=start` is logged but has no other effect since STT is already stopped by the time it arrives.

**App → backend** — video ended, sent when a device instruction video finishes playing:
```json
{"type": "video_ended"}
```

This releases the STT hold so that the user can say "ready" immediately after the video finishes.

## Key Design Decisions

- **All dialogue strings live in `config.py`** (`PAGE_CONFIG`). Edit messages there – do not hardcode strings elsewhere.
- **Questionnaire questions (Q1/Q2/Q3)** re-prompt inline on invalid input; they never trigger the sorry page. Any question can be skipped (recorded as `"skipped"`).
- **The sorry page is triggered by device timeouts only**, not by user confusion or invalid input. Off-topic or unclear responses at any confirmation step are handled by `LLMHelper.evaluate_proceed()`, which generates a helpful reply and re-prompts within the same state.
- **Device readings** block on a queue (`device_queue.get(timeout=30)`). For demo purposes, `simulate_reading()` in `device.py` auto-fires a fake reading. Remove that call in `robot.py` when connecting real hardware.

## Configuration (`config.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `READING_TIMEOUT` | 30s | Seconds before a device reading times out |
| `MAX_RETRIES` | 3 | Consecutive sorry-retries before returning to idle |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model used for intent detection |
| `LLM_TEMPERATURE` | 0.0 | LLM temperature (0.0 = deterministic) |
