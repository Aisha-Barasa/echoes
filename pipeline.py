"""
Echoes pipeline: turns a stream of independent citizen reports into
clustered, confidence-scored community events.

Design:
  1. Deterministic pre-filter (geo + time window) narrows candidate events.
     This keeps the system fast and predictable -- we never ask Gemma to
     compare a new report against every historical report.
  2. Gemma 4 makes the semantic join/no-join decision over the narrowed
     candidate set (see gemma_client.py), using function calling to pull
     in weather and (mocked) satellite context.
  3. Confidence is a transparent, deterministic formula -- not a number
     Gemma reports about itself -- so it's auditable and reproducible.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import gemma_client

GEO_RADIUS_M = 1500        # candidate events must be within this radius
TIME_WINDOW_S = 150 * 60   # ...and within this many seconds of the last report
ALERT_CONFIDENCE = 0.90
ALERT_MIN_REPORTS = 3


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Report:
    id: str
    ts: float                # unix seconds
    lat: float
    lon: float
    landmark: str
    modality: str            # "text" | "voice" | "photo"
    text: str
    language: str = "en"
    image_desc: Optional[str] = None


@dataclass
class Event:
    id: str
    title: str
    pollution_type: str
    report_ids: list = field(default_factory=list)
    modalities: set = field(default_factory=set)
    centroid_lat: float = 0.0
    centroid_lon: float = 0.0
    first_ts: float = 0.0
    last_ts: float = 0.0
    semantic_scores: list = field(default_factory=list)
    confidence: float = 0.0
    alert_fired: bool = False
    rationale_log: list = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "pollution_type": self.pollution_type,
            "report_count": len(self.report_ids),
            "modalities": sorted(self.modalities),
            "confidence": round(self.confidence, 3),
            "alert_fired": self.alert_fired,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "rationale_log": self.rationale_log,
        }


class EventStore:
    def __init__(self):
        self.events: dict[str, Event] = {}
        self.reports: dict[str, Report] = {}
        self.timeline: list[dict] = []  # feed of everything that happened, for the UI

    # ---- deterministic pre-filter -------------------------------------
    def candidate_events(self, report: Report) -> list[Event]:
        out = []
        for ev in self.events.values():
            if abs(report.ts - ev.last_ts) > TIME_WINDOW_S:
                continue
            if haversine_m(report.lat, report.lon, ev.centroid_lat, ev.centroid_lon) > GEO_RADIUS_M:
                continue
            out.append(ev)
        return out

    # ---- confidence scoring --------------------------------------------
    def score_confidence(self, ev: Event) -> float:
        n = len(ev.report_ids)
        report_count_term = min(n / 6, 1.0) * 0.35

        modality_term = min(len(ev.modalities) / 3, 1.0) * 0.20

        rpts = [self.reports[rid] for rid in ev.report_ids]
        if len(rpts) >= 2:
            max_d = max(
                haversine_m(a.lat, a.lon, b.lat, b.lon)
                for i, a in enumerate(rpts) for b in rpts[i + 1:]
            )
            geo_term = (1 - min(max_d / GEO_RADIUS_M, 1.0)) * 0.15
        else:
            geo_term = 0.15

        span = ev.last_ts - ev.first_ts
        time_term = (1 - min(span / TIME_WINDOW_S, 1.0)) * 0.15

        semantic_term = (sum(ev.semantic_scores) / len(ev.semantic_scores) if ev.semantic_scores else 0.6) * 0.15

        return round(report_count_term + modality_term + geo_term + time_term + semantic_term, 3)

    # ---- ingest one report ----------------------------------------------
    def ingest(self, report: Report) -> dict:
        self.reports[report.id] = report
        candidates = self.candidate_events(report)

        decision = gemma_client.classify_report(report, candidates)

        if decision["action"] == "join" and decision["event_id"] in self.events:
            ev = self.events[decision["event_id"]]
        else:
            ev = Event(
                id=str(uuid.uuid4())[:8],
                title=decision.get("pollution_type", "Unclassified event").title(),
                pollution_type=decision.get("pollution_type", "unknown"),
                centroid_lat=report.lat,
                centroid_lon=report.lon,
                first_ts=report.ts,
            )
            self.events[ev.id] = ev

        ev.report_ids.append(report.id)
        ev.modalities.add(report.modality)
        ev.last_ts = report.ts
        ev.semantic_scores.append(decision.get("semantic_match_score", 0.6))
        # recompute centroid as running average
        rpts = [self.reports[rid] for rid in ev.report_ids]
        ev.centroid_lat = sum(r.lat for r in rpts) / len(rpts)
        ev.centroid_lon = sum(r.lon for r in rpts) / len(rpts)

        ev.confidence = self.score_confidence(ev)
        ev.rationale_log.append(decision.get("rationale", ""))

        newly_alerted = False
        if (not ev.alert_fired
                and ev.confidence >= ALERT_CONFIDENCE
                and len(ev.report_ids) >= ALERT_MIN_REPORTS):
            ev.alert_fired = True
            newly_alerted = True

        entry = {
            "report": {
                "id": report.id, "ts": report.ts, "modality": report.modality,
                "text": report.text, "landmark": report.landmark, "language": report.language,
            },
            "event_id": ev.id,
            "decision": decision,
            "confidence_after": ev.confidence,
            "alert_fired_now": newly_alerted,
        }
        self.timeline.append(entry)
        return entry

    def state(self) -> dict:
        return {
            "timeline": self.timeline,
            "events": [ev.to_dict() for ev in self.events.values()],
        }
