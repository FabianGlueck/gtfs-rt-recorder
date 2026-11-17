"""Holt einen GTFS-RT-Snapshot und speichert den Stuttgart-Ausschnitt verlustfrei als Protobuf.

Ablage: data/rt/YYYY-MM-DD/HHMMSSZ.pb.gz (UTC, Zeitpunkt des Abrufs)
Index:  data/index/YYYY-MM-DD.csv (eine Zeile pro Snapshot, auch für die Volumen-Hochrechnung)

Gefiltert wird gegen die beiden jüngsten Static-Versionen, damit beim Versionswechsel
(RT- und Static-Feed wechseln nicht unbedingt gleichzeitig) nichts verloren geht.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2 as pb

from recorder.config import CURRENT, INDEX_DIR, RT_DIR, RT_URL, STATIC_DIR, USER_AGENT

INDEX_FIELDS = [
    "fetched_at_utc", "file", "header_timestamp", "feed_age_s", "last_modified", "etag",
    "bytes_raw", "entities_total", "trip_updates_total", "alerts_total",
    "trip_updates_kept", "alerts_kept", "stop_time_updates_kept", "bytes_kept_gz",
    "static_versions", "fetch_seconds", "attempts",
]


def load_filter() -> tuple[set[str], set[str], set[str], list[str]]:
    versions = sorted(p.name for p in STATIC_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not versions or not CURRENT.exists():
        raise SystemExit("kein Static-Ausschnitt vorhanden, erst recorder.static_subset laufen lassen")
    use = versions[-2:]
    trips: set[str] = set()
    stops: set[str] = set()
    routes: set[str] = set()
    for v in use:
        d = STATIC_DIR / v
        stops |= set((d / "bbox_stop_ids.txt").read_text().split())
        with gzip.open(d / "trips.txt.gz", "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                trips.add(r["trip_id"])
                routes.add(r["route_id"])
    return trips, stops, routes, use


def fetch() -> tuple[bytes, dict, float, int]:
    last_err = None
    for attempt in range(1, 5):
        t0 = time.time()
        try:
            req = urllib.request.Request(RT_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
                headers = dict(r.headers)
            expected = headers.get("Content-Length")
            if expected and int(expected) != len(body):
                raise IOError(f"unvollständig: {len(body)} von {expected} Bytes")
            return body, headers, time.time() - t0, attempt
        except Exception as e:  # noqa: BLE001 - jeder Fehler -> erneut versuchen
            last_err = e
            print(f"Abruf {attempt} fehlgeschlagen: {e}", file=sys.stderr)
            time.sleep(10 * attempt)
    raise SystemExit(f"Abruf endgültig fehlgeschlagen: {last_err}")


def alert_matches(alert, trips, stops, routes) -> bool:
    for ie in alert.informed_entity:
        if ie.stop_id and ie.stop_id in stops:
            return True
        if ie.route_id and ie.route_id in routes:
            return True
        if ie.HasField("trip") and ie.trip.trip_id in trips:
            return True
    return False


def main() -> int:
    trips, stops, routes, versions = load_filter()
    body, headers, fetch_s, attempts = fetch()
    fetched = datetime.now(timezone.utc)

    feed = pb.FeedMessage()
    feed.ParseFromString(body)

    out = pb.FeedMessage()
    out.header.CopyFrom(feed.header)
    tu_total = al_total = tu_kept = al_kept = stu_kept = 0
    for e in feed.entity:
        if e.HasField("trip_update"):
            tu_total += 1
            tu = e.trip_update
            if tu.trip.trip_id in trips or any(s.stop_id in stops for s in tu.stop_time_update):
                out.entity.append(e)
                tu_kept += 1
                stu_kept += len(tu.stop_time_update)
        elif e.HasField("alert"):
            al_total += 1
            if alert_matches(e.alert, trips, stops, routes):
                out.entity.append(e)
                al_kept += 1
        elif e.HasField("vehicle"):
            # aktuell nicht im Feed; falls doch, mitnehmen, wenn die Fahrt passt
            if e.vehicle.trip.trip_id in trips:
                out.entity.append(e)

    day = fetched.strftime("%Y-%m-%d")
    name = fetched.strftime("%H%M%SZ") + ".pb.gz"
    day_dir = RT_DIR / day
    day_dir.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress(out.SerializeToString(), compresslevel=9, mtime=0)
    (day_dir / name).write_bytes(payload)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    idx_path = INDEX_DIR / f"{day}.csv"
    new = not idx_path.exists()
    row = {
        "fetched_at_utc": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": f"rt/{day}/{name}",
        "header_timestamp": feed.header.timestamp,
        "feed_age_s": int(fetched.timestamp() - feed.header.timestamp) if feed.header.timestamp else "",
        "last_modified": headers.get("Last-Modified", ""),
        "etag": headers.get("ETag", "").strip('"'),
        "bytes_raw": len(body),
        "entities_total": len(feed.entity),
        "trip_updates_total": tu_total,
        "alerts_total": al_total,
        "trip_updates_kept": tu_kept,
        "alerts_kept": al_kept,
        "stop_time_updates_kept": stu_kept,
        "bytes_kept_gz": len(payload),
        "static_versions": "+".join(versions),
        "fetch_seconds": round(fetch_s, 1),
        "attempts": attempts,
    }
    with open(idx_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    print(json.dumps(row, indent=2))

    if tu_total and tu_kept / tu_total < 0.005:
        # Plausibilitätswarnung: vermutlich passen trip_ids nicht mehr zum Static-Ausschnitt
        print(f"::warning::nur {tu_kept}/{tu_total} Fahrten behalten, Static-Version prüfen", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
