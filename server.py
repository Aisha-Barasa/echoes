import os
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from pipeline import EventStore, Report
from demo_reports import REPORTS, BASE_LAT, BASE_LON

app = Flask(__name__, static_folder="static")
store = EventStore()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Preset landmarks so live-submitted reports still fall inside the same
# geo cluster as the scripted demo reports (a real deployment would use
# actual GPS from the submitter's phone instead of a dropdown).
LANDMARKS = {
    "Kongowea Market - fish section": (BASE_LAT + 0.0001, BASE_LON + 0.0002),
    "Kongowea Market - main gate": (BASE_LAT + 0.0005, BASE_LON - 0.0004),
    "Kongowea Market - back alley": (BASE_LAT + 0.0009, BASE_LON + 0.0007),
    "Near Kongowea health post": (BASE_LAT - 0.0002, BASE_LON + 0.0003),
    "Kongowea, opposite the bus stage": (BASE_LAT + 0.0003, BASE_LON - 0.0002),
    "Other / not listed": (BASE_LAT, BASE_LON),
}

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


@app.route("/report")
def report_page():
    return send_from_directory("static", "report.html")


@app.route("/api/landmarks")
def api_landmarks():
    return jsonify(sorted(LANDMARKS.keys()))


@app.route("/api/submit_report", methods=["POST"])
def api_submit_report():
    text = request.form.get("text", "").strip()
    modality = request.form.get("modality", "text")
    language = request.form.get("language", "en")
    landmark = request.form.get("landmark", "Other / not listed")
    image_desc = request.form.get("image_desc", "").strip() or None

    if not text and not image_desc:
        return jsonify({"error": "Report needs some text or a photo description."}), 400

    lat, lon = LANDMARKS.get(landmark, (BASE_LAT, BASE_LON))

    image_url = None
    photo = request.files.get("photo")
    if photo and photo.filename:
        filename = f"{uuid.uuid4().hex[:8]}_{secure_filename(photo.filename)}"
        photo.save(os.path.join(UPLOAD_DIR, filename))
        image_url = f"/static/uploads/{filename}"

    report = Report(
        id=f"live-{uuid.uuid4().hex[:8]}",
        ts=time.time(),
        lat=lat, lon=lon, landmark=landmark,
        modality=modality, text=text or "(photo report)",
        language=language, image_desc=image_desc,
    )
    with _lock:
        entry = store.ingest(report)
        entry["image_url"] = image_url
        store.timeline[-1]["image_url"] = image_url

    return jsonify({"ok": True, "event_id": entry["event_id"], "confidence": entry["confidence_after"]})


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
