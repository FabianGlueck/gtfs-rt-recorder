"""Baut den Stuttgart-Ausschnitt des Static-GTFS, falls gtfs.de eine neue Version hat.

Ergebnis: data/static/<version>/*.txt.gz (Ausschnitt) + data/static/current.json.
Die RT-trip_ids sind nur zusammen mit dem passenden Static-Feed interpretierbar,
deshalb wird jede Version archiviert und nicht überschrieben.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from email.utils import parsedate_to_datetime
from pathlib import Path

from recorder.config import BBOX, CURRENT, STATIC_DIR, STATIC_URL, USER_AGENT

csv.field_size_limit(sys.maxsize)


def remote_version() -> tuple[str, str]:
    req = urllib.request.Request(STATIC_URL, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        lm = r.headers["Last-Modified"]
    dt = parsedate_to_datetime(lm)
    return dt.strftime("%Y-%m-%dT%H%M%SZ"), lm


def local_version() -> str | None:
    if not CURRENT.exists():
        return None
    return json.loads(CURRENT.read_text())["version"]


def download(dest: Path) -> None:
    req = urllib.request.Request(STATIC_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)


def rows(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        header = next(reader)
        yield header
        yield from reader


def filter_file(zf, name, out_dir, keep) -> int:
    """Schreibt name gefiltert (keep(header_idx, row) -> bool) als .gz. Gibt Zeilenzahl zurück."""
    if name not in zf.namelist():
        return 0
    it = rows(zf, name)
    header = next(it)
    idx = {h: i for i, h in enumerate(header)}
    n = 0
    with gzip.open(out_dir / f"{name}.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in it:
            if keep(idx, row):
                w.writerow(row)
                n += 1
    return n


def build(zip_path: Path, version: str, last_modified: str) -> dict:
    t0 = time.time()
    out = STATIC_DIR / version
    tmp_out = STATIC_DIR / f".{version}.tmp"
    shutil.rmtree(tmp_out, ignore_errors=True)
    tmp_out.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        # 1) Haltestellen in der Bounding Box
        it = rows(zf, "stops.txt")
        h = {k: i for i, k in enumerate(next(it))}
        bbox_stops: set[str] = set()
        parent_of: dict[str, str] = {}
        for r in it:
            try:
                lat, lon = float(r[h["stop_lat"]]), float(r[h["stop_lon"]])
            except (ValueError, IndexError):
                continue
            if "parent_station" in h and r[h["parent_station"]]:
                parent_of[r[h["stop_id"]]] = r[h["parent_station"]]
            if BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lon_min"] <= lon <= BBOX["lon_max"]:
                bbox_stops.add(r[h["stop_id"]])

        # 2) Fahrten, die mindestens eine dieser Haltestellen bedienen
        it = rows(zf, "stop_times.txt")
        h = {k: i for i, k in enumerate(next(it))}
        si, ti = h["stop_id"], h["trip_id"]
        trips: set[str] = set()
        total_stop_times = 0
        for r in it:
            total_stop_times += 1
            if r[si] in bbox_stops:
                trips.add(r[ti])

        # 3) Volle stop_times dieser Fahrten (auch Halte außerhalb der Box)
        used_stops: set[str] = set()

        def keep_st(idx, r):
            if r[idx["trip_id"]] in trips:
                used_stops.add(r[idx["stop_id"]])
                return True
            return False

        n_st = filter_file(zf, "stop_times.txt", tmp_out, keep_st)

        routes: set[str] = set()
        services: set[str] = set()

        def keep_trip(idx, r):
            if r[idx["trip_id"]] in trips:
                routes.add(r[idx["route_id"]])
                services.add(r[idx["service_id"]])
                return True
            return False

        n_trips = filter_file(zf, "trips.txt", tmp_out, keep_trip)

        agencies: set[str] = set()

        def keep_route(idx, r):
            if r[idx["route_id"]] in routes:
                if "agency_id" in idx:
                    agencies.add(r[idx["agency_id"]])
                return True
            return False

        n_routes = filter_file(zf, "routes.txt", tmp_out, keep_route)
        filter_file(zf, "agency.txt", tmp_out, lambda idx, r: "agency_id" not in idx or r[idx["agency_id"]] in agencies)
        filter_file(zf, "calendar.txt", tmp_out, lambda idx, r: r[idx["service_id"]] in services)
        filter_file(zf, "calendar_dates.txt", tmp_out, lambda idx, r: r[idx["service_id"]] in services)

        keep_stop_ids = used_stops | bbox_stops
        keep_stop_ids |= {parent_of[s] for s in keep_stop_ids if s in parent_of}
        n_stops = filter_file(zf, "stops.txt", tmp_out, lambda idx, r: r[idx["stop_id"]] in keep_stop_ids)
        for extra in ("feed_info.txt", "attributions.txt"):
            filter_file(zf, extra, tmp_out, lambda idx, r: True)

    (tmp_out / "bbox_stop_ids.txt").write_text("\n".join(sorted(bbox_stops)) + "\n")

    meta = {
        "version": version,
        "last_modified": last_modified,
        "source": STATIC_URL,
        "bbox": BBOX,
        "bbox_stops": len(bbox_stops),
        "trips": n_trips,
        "routes": n_routes,
        "stops": n_stops,
        "stop_times": n_st,
        "stop_times_total_germany": total_stop_times,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build_seconds": round(time.time() - t0, 1),
    }
    (tmp_out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    shutil.rmtree(out, ignore_errors=True)
    tmp_out.rename(out)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--zip", type=Path, help="lokale Static-ZIP statt Download (zum Testen)")
    args = ap.parse_args()

    version, lm = remote_version()
    if not args.force and local_version() == version:
        print(f"static: aktuell ({version})")
        return 0

    print(f"static: neue Version {version} (lokal: {local_version()}), baue Ausschnitt …", flush=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    if args.zip:
        meta = build(args.zip, version, lm)
    else:
        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "static.zip"
            download(zp)
            meta = build(zp, version, lm)
    CURRENT.write_text(json.dumps({"version": version, "last_modified": lm}, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
