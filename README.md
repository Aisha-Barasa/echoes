# Echoes — Build with Gemma  
## Track 2: CleanAir & Clear Streets

🔗 **[Deployed Link](https://echoes-t5je.onrender.com/)** · 🎥 **[Demo Video](https://youtu.be/ccNhTVFltsE)**

**"When one person speaks, a community is heard."**

Echoes doesn't ask *what does this report mean*. It asks *which reports
belong together*. Citizens submit pollution reports as text, voice, or
photos, in English or Swahili. Gemma 4 decides whether each new report
describes an existing community event or a new one — using function
calling to pull in live weather and (mocked) satellite context — and a
transparent, deterministic confidence score climbs until the county
dashboard fires an alert.

This repo ships one rehearsed happy path: a garbage fire near Kongowea
Market, Mombasa, told through six reports arriving over ~25 minutes.

## See it in action

<img width="400" height="451" alt="e1" src="https://github.com/user-attachments/assets/02ffaeb6-9d32-4340-8576-4dacfb470d4b" />

Citizens submit through a real, working public page — no login, no app to
install. Voice notes are transcribed live in the browser


<img width="1336" height="590" alt="e2" src="https://github.com/user-attachments/assets/8f4368d9-0af3-43a3-850f-bfa565c30525" />

A single report opens a new event at modest confidence — the system
correctly recognizes it doesn't yet match anything nearby closely enough
to join, and starts fresh rather than forcing a false match. Confidence
climbs as more independent reports arrive (see below)


<img width="1342" height="586" alt="e3" src="https://github.com/user-attachments/assets/dad994f6-f07f-418f-b16c-83196db96bc6" />

Confidence at its peak: six scripted reports plus one live submission —
"There is smoke near Kongowea market," worded differently from every
other report — correctly joined the same event rather than starting a
new one. The alert fires once confidence crosses 90% with at least three
independent reports.



## Architecture

```
citizen reports (text / voice transcript / photo)
        │
        ▼
deterministic pre-filter (pipeline.py)
  — candidate events within 1.5km and 150 minutes
        │
        ▼
Gemma 4 semantic join/no-join decision (gemma_client.py)
  — function calling: get_weather() [real, live], get_satellite_hotspot() [mocked]
        │
        ▼
deterministic confidence score (pipeline.py: score_confidence)
  — report count, modality diversity, geo tightness, time tightness, semantic match
        │
        ▼
county dashboard (static/dashboard.html)
  — live feed + confidence ring + alert banner
```

We deliberately split this into a **deterministic layer** (pre-filter,
scoring, alerting) and a **model layer** (the semantic join decision).
This keeps the system fast, auditable, and resistant to a single bad
model call — but the actual clustering intelligence is Gemma's.

## What's real vs mocked (full disclosure)

- **Gemma 4 function calling** — real. `gemma_client.py` calls a local
  Gemma 4 model through Ollama's OpenAI-compatible endpoint with two
  tools (`get_weather`, `get_satellite_hotspot`).
- **Weather** — real, live call to Open-Meteo (no API key required).
- **Satellite hotspot detection** — **mocked**. A production version
  would query NASA FIRMS; we stub it to `fire_detected: false` 
- **Offline fallback classifier** — if Ollama isn't reachable (no GPU,
  model not pulled), a small deterministic keyword classifier takes
  over so the demo never stalls on a live model dependency. This is
  logged loudly every time it fires and is not used to disguise the
  absence of a real Gemma integration — it's a resilience fallback for
  a demo.

## Running it

```bash
pip install flask

# Optional but recommended — real Gemma 4 path:
# ollama pull gemma3:4b   (or your local Gemma 4 tag)
# ollama serve

python3 server.py
# open http://localhost:5050
```

The scripted six-report sequence starts automatically and runs on a
20x time-compression (`DEMO_SPEED` in `server.py`) so the ~25-minute
real-world timeline plays out in about 80 seconds for a live demo.
`POST /api/reset` restarts it (handy for re-running in front of judges).

## Confidence formula

We chose a transparent formula over asking Gemma to self-report a
number, because LLM-reported confidence isn't reliably calibrated:

| Signal | Weight |
|---|---|
| Report count (caps at 6) | 0.35 |
| Modality diversity (text/voice/photo) | 0.20 |
| Geographic tightness of the cluster | 0.15 |
| Time tightness of the cluster | 0.15 |
| Average Gemma semantic-match score | 0.15 |

Alert fires at confidence ≥ 0.90 with ≥ 3 independent reports.

## Files

- `pipeline.py` — event store, geo/time pre-filter, confidence scoring
- `gemma_client.py` — Gemma 4 function-calling client + tool implementations
- `demo_reports.py` — the scripted six-report happy path
- `server.py` — Flask app serving the dashboard and feeding the demo
- `static/dashboard.html` — county dashboard UI

  **"When one person speaks, it's a report."**
  
  **"When a community speaks, it is impossible to ignore."**
