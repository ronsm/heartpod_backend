"""
HTTP interface for the Android app.

GET  /state  → {"page_id": N, "data": {...}}   – polled by the Android app
POST /action → {"action": "...", "data": {...}} – button presses from the app

Button actions are mapped to natural-language phrases that the LLM pipeline
understands; questionnaire answers are passed through as-is.
"""

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

DEFAULT_PORT = 8000

# Shared state: read by GET /state, written by robot._set_page()
_http_state: dict = {"page_id": 1, "data": {}}
_http_state_lock = threading.Lock()

# Actions from the Android app (and terminal) are placed here;
# robot._ask_user() blocks on this queue.
action_queue: queue.Queue = queue.Queue()

# Maps UI action keywords to natural-language phrases the LLM understands.
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

    def do_POST(self):
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        action = body.get("action", "")
        data = body.get("data", {})
        # Answers carry the full option text; everything else maps via the table.
        if action == "answer":
            text = data.get("answer", action)
        else:
            text = _ACTION_TEXT.get(action, action)
        if text:
            action_queue.put(text)
            print(f"\n  [app] '{text}'" + (f"  ({action})" if action != text else ""))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress per-request logs


def update_state(page_id: int, data: dict):
    """Push the current page to _http_state so the Android app picks it up."""
    with _http_state_lock:
        _http_state["page_id"] = page_id
        _http_state["data"] = data


def start_http_server(port: int = DEFAULT_PORT) -> HTTPServer:
    """Start the HTTP server in a background daemon thread. Returns the server instance."""
    server = HTTPServer(("0.0.0.0", port), _HttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
