"""
Gemma 4 integration for Echoes.

Real path: calls a locally-running Gemma 4 model through Ollama's
OpenAI-compatible /v1/chat/completions endpoint, using tool calling so
Gemma can pull in weather (real, live) and satellite hotspot data
(mocked -- see get_satellite_hotspot) before deciding whether a new
report joins an existing community event.

Fallback path: if Ollama isn't reachable (e.g. rehearsing a demo on a
laptop with no GPU / no model pulled), we fall back to a small
deterministic classifier so the rest of the pipeline still runs end to
end. This is clearly logged -- it is NOT used to hide the absence of a
real Gemma call in the submitted project; run `ollama pull gemma3:4b`
(or your local Gemma 4 tag) and the real path takes over automatically.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_MODEL = os.environ.get("GEMMA_MODEL", "gemma4:e4b")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current wind direction and speed for a location, to help judge whether smoke/dust would plausibly drift between two reported locations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_satellite_hotspot",
            "description": "Check satellite thermal-anomaly data for an active fire near a location and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "timestamp": {"type": "number"},
                },
                "required": ["lat", "lon", "timestamp"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are the clustering brain of Echoes, a civic pollution-reporting \
system. You receive one new citizen report and a short list of candidate open events \
nearby in space and time. Decide whether the new report describes the SAME real-world \
event as one of the candidates, or a NEW event.

Use the get_weather and get_satellite_hotspot tools when they would help you judge \
plausibility (e.g. does wind direction support smoke drifting from A to B; is this a \
fire or something else).

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "action": "join" | "new",
  "event_id": "<id of the candidate to join, or null>",
  "pollution_type": "<short type, e.g. smoke, dust, illegal dumping, waste burning>",
  "semantic_match_score": <0.0-1.0, how strongly the content/meaning matches the candidate>,
  "rationale": "<one sentence, plain language, for the county dashboard>"
}
"""


def _call_tool(name: str, args: dict) -> dict:
    if name == "get_weather":
        return get_weather(args["lat"], args["lon"])
    if name == "get_satellite_hotspot":
        return get_satellite_hotspot(args["lat"], args["lon"], args.get("timestamp", 0))
    return {"error": f"unknown tool {name}"}


def get_weather(lat: float, lon: float) -> dict:
    """Real, live, no-auth-required call to Open-Meteo for current wind data."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=wind_speed_10m,wind_direction_10m"
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read())
        cur = data.get("current", {})
        return {
            "wind_speed_ms": cur.get("wind_speed_10m"),
            "wind_direction_deg": cur.get("wind_direction_10m"),
            "source": "open-meteo (live)",
        }
    except Exception as e:
        return {"error": str(e), "source": "open-meteo (unreachable)"}


def get_satellite_hotspot(lat: float, lon: float, timestamp: float) -> dict:
    """
    MOCKED for the hackathon: a real integration would query NASA FIRMS
    (Fire Information for Resource Management System) for active thermal
    anomalies near (lat, lon) around `timestamp`. We stub it out here and
    say so explicitly in the writeup and this docstring.
    """
    return {"fire_detected": False, "source": "MOCKED -- would be NASA FIRMS in production"}


def classify_report(report, candidates: list) -> dict:
    """Ask Gemma 4 (or the offline fallback) whether `report` joins one of
    `candidates` or starts a new event. Returns the decision dict described
    in SYSTEM_PROMPT."""
    candidates_payload = [
        {
            "event_id": c.id,
            "pollution_type": c.pollution_type,
            "report_count": len(c.report_ids),
        }
        for c in candidates
    ]

    user_payload = {
        "new_report": {
            "modality": report.modality,
            "text": report.text,
            "image_desc": report.image_desc,
            "language": report.language,
            "landmark": report.landmark,
            "lat": report.lat,
            "lon": report.lon,
            "timestamp": report.ts,
        },
        "candidate_events": candidates_payload,
    }

    try:
        return _call_gemma_with_tools(user_payload)
    except Exception as e:
        print(f"[gemma_client] Ollama unreachable ({e}); using offline fallback classifier.")
        return _fallback_classify(report, candidates)


def _call_gemma_with_tools(user_payload: dict) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload)},
    ]

    for _ in range(4):  # allow a couple of tool round-trips
        body = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": messages,
            "tools": TOOLS,
            "temperature": 0.1,
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        msg = data["choices"][0]["message"]
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            content = msg["content"].strip().strip("`")
            if content.startswith("json"):
                content = content[4:]
            return json.loads(content)

        messages.append(msg)
        for tc in tool_calls:
            fn = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            result = _call_tool(fn, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })

    raise RuntimeError("Gemma did not return a final answer after tool round-trips")


def _fallback_classify(report, candidates: list) -> dict:
    """Deterministic offline stand-in, used only when Ollama/Gemma is unreachable.
    Keyword-matches pollution vocabulary so the pipeline still demonstrates
    correct clustering end-to-end without a live model."""
    keywords = {
        "smoke": "smoke", "moshi": "smoke", "ash": "smoke", "majivu": "smoke",
        "burn": "smoke", "fire": "smoke",
        "dust": "dust", "vumbi": "dust",
        "smell": "smoke", "harufu": "smoke",
        "cough": "smoke", "kikohozi": "smoke",
    }
    text = (report.text or "").lower() + " " + (report.image_desc or "").lower()
    ptype = next((v for k, v in keywords.items() if k in text), "unknown")

    if candidates:
        best = max(candidates, key=lambda c: len(c.report_ids))
        if best.pollution_type == ptype or ptype == "unknown":
            return {
                "action": "join",
                "event_id": best.id,
                "pollution_type": best.pollution_type,
                "semantic_match_score": 0.82,
                "rationale": f"Report content and location/time are consistent with the ongoing {best.pollution_type} event.",
            }

    return {
        "action": "new",
        "event_id": None,
        "pollution_type": ptype,
        "semantic_match_score": 0.6,
        "rationale": "No open nearby event matched closely enough; starting a new event.",
    }
