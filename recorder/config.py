"""Gemeinsame Konfiguration für Recorder und Static-Subset."""

from pathlib import Path

RT_URL = "https://realtime.gtfs.de/realtime-free.pb"
STATIC_URL = "https://download.gtfs.de/germany/free/latest.zip"

# Bewusst großzügiger als „Stuttgart Stadt“: ungefähr das VVS-Gebiet
# (Stuttgart + Landkreise BB, ES, LB, WN). Die Haltestellen-/Linienauswahl
# ist noch offen (R5); fehlende Historie lässt sich nicht nachholen, daher eher zu viel aufzeichnen.
BBOX = {
    "lat_min": 48.55,
    "lat_max": 49.05,
    "lon_min": 8.80,
    "lon_max": 9.75,
}

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATIC_DIR = DATA / "static"
RT_DIR = DATA / "rt"
INDEX_DIR = DATA / "index"
CURRENT = STATIC_DIR / "current.json"

USER_AGENT = "gtfs-rt-recorder (studentisches Projekt)"
