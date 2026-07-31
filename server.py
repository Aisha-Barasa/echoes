import threading
import time

from flask import Flask, jsonify, send_from_directory

from pipeline import EventStore, Report
from demo_reports import REPORTS

app = Flask(__name__, static_folder="static")
store = EventStore()

DEMO_SPEED = 20     # real-time divisor: 5 real seconds stands in for ~100 demo seconds
_lock = threading.Lock()
_started_at = None
_thread = None


def _feed_reports():
    global _started_at
    _started_at = time.time()
    for i, r in enumerate(REPORTS):
        delay = r["offset_s"] / DEMO_SPEED
        if i > 0:
            prev_delay = REPORTS[i - 1]["offset_s"] / DEMO_SPEED
            time.sleep(max(delay - prev_delay, 0.5))
        report = Report(
            id=f"r{i}",
            ts=time.time(),
            lat=r["lat"], lon=r["lon"], landmark=r["landmark"],
            modality=r["modality"], text=r["text"], language=r["language"],
            image_desc=r.get("image_desc"),
        )
        with _lock:
            store.ingest(report)


@app.route("/")
def index():
    return send_from_directory("static", "dashboard.html")


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify(store.state())


@app.route("/api/reset", methods=["POST"])
def api_reset():
    global store, _thread
    with _lock:
        store = EventStore()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_feed_reports, daemon=True)
        _thread.start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    _thread = threading.Thread(target=_feed_reports, daemon=True)
    _thread.start()
    app.run(host="0.0.0.0", port=5050, debug=False)
