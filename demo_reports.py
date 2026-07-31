"""
The rehearsed happy path: six reports, ~4 minutes apart, all describing
one real event (a garbage fire near Kongowea Market, Mombasa) through
different modalities and languages. Feed these through pipeline.ingest()
in order and Echoes should cluster all six into one event, with
confidence climbing past the alert threshold by report #4 or #5.

Timestamps are offsets in seconds from t0; server.py adds time.time().
"""

BASE_LAT, BASE_LON = -4.0518, 39.6636  # Kongowea Market, Mombasa

REPORTS = [
    dict(
        offset_s=0, lat=BASE_LAT + 0.0006, lon=BASE_LON + 0.0004,
        landmark="Kongowea Market, near the fish section",
        modality="text", language="en",
        text="There's smoke coming from behind the market stalls, looks like someone burning rubbish.",
    ),
    dict(
        offset_s=5 * 60, lat=BASE_LAT + 0.0003, lon=BASE_LON - 0.0002,
        landmark="Kongowea, opposite the bus stage",
        modality="text", language="sw-en",
        text="Kuna harufu mbaya sana ya moshi hapa Kongowea, imekuwa ikiendelea for like 20 minutes.",
    ),
    dict(
        offset_s=11 * 60, lat=BASE_LAT + 0.0009, lon=BASE_LON + 0.0007,
        landmark="Kongowea Market, back alley",
        modality="photo", language="en",
        text="Photo uploaded from the market back alley.",
        image_desc="Thick grey smoke rising from a pile of burning garbage between two market stalls, no visible flame damage to structures.",
    ),
    dict(
        offset_s=16 * 60, lat=BASE_LAT - 0.0002, lon=BASE_LON + 0.0003,
        landmark="Near Kongowea health post",
        modality="voice", language="en",
        text="Voice note transcript: my daughter has started coughing since this morning, the air near the market is really thick and it's not clearing up.",
    ),
    dict(
        offset_s=21 * 60, lat=BASE_LAT + 0.0005, lon=BASE_LON - 0.0004,
        landmark="Kongowea Market, main gate",
        modality="text", language="en",
        text="Still smoky at the market main gate, shopkeepers are closing early because of the smell.",
    ),
    dict(
        offset_s=26 * 60, lat=BASE_LAT + 0.0001, lon=BASE_LON + 0.0002,
        landmark="Kongowea Market, fish section",
        modality="text", language="sw-en",
        text="Moshi bado iko pale market, mtu should send fire brigade before it spreads to the stalls.",
    ),
]
