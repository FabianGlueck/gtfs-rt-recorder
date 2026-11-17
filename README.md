# gtfs-rt-recorder

Zeichnet den Stuttgart-Ausschnitt (≈ VVS-Gebiet) des GTFS-RT-Feeds von gtfs.de auf,
als Historie für das Erwartungsmodell in A1 (Big Data Engineering, DHBW).
Hintergrund: Leitstand ADR 0020, 0023, Risiko R15.

## Was passiert

GitHub Actions (`.github/workflows/record.yml`) läuft alle 30 min:

1. `recorder.static_subset`: prüft per HEAD, ob gtfs.de einen neuen Static-Feed hat. Falls ja: Download (~280 MB),
   Ausschnitt bauen (Haltestellen in der Bounding Box, alle Fahrten, die dort halten, samt kompletter
   `stop_times`, `trips`, `routes`, `calendar*`, `agency`) → `data/static/<version>/`.
2. `recorder.snapshot`: holt den RT-Feed (bundesweit, ~30 MB), behält Trip-Updates und Alerts mit Bezug
   zum Ausschnitt und speichert sie **unverändert als Protobuf** → `data/rt/YYYY-MM-DD/HHMMSSZ.pb.gz`.
   Gefiltert wird gegen die zwei jüngsten Static-Versionen (Versionswechsel).
3. Commit + Push.

Pro Snapshot eine Zeile in `data/index/YYYY-MM-DD.csv`: Rohgröße, Entitäten gesamt/behalten, Feed-Alter usw.
Das ist auch die Datengrundlage für die Volumen-Hochrechnung auf den Gesamtfeed (ADR 0018).

## Warum 30 Minuten

Privates Repo auf GitHub Free: ~2000 Actions-Minuten pro Monat, jeder Lauf wird auf eine Minute aufgerundet.
48 Läufe/Tag ≈ 1500 min/Monat. Der Feed enthält zu jeder laufenden Fahrt auch die vergangenen Halte, deshalb
reicht ein Snapshot, solange beendete Fahrten länger als das Intervall im Feed bleiben.

## Replay

```python
import gzip
from google.transit import gtfs_realtime_pb2 as pb
f = pb.FeedMessage()
f.ParseFromString(gzip.decompress(open("data/rt/2026-11-18/081100Z.pb.gz", "rb").read()))
```

Zum Interpretieren der `trip_id`s die Static-Version aus `static_versions` im Index nehmen.

## Lokal

```bash
uv venv && uv pip install -r requirements.txt
uv run python -m recorder.static_subset          # oder --zip pfad/latest.zip
uv run python -m recorder.snapshot
```

## Lizenz der Daten

GTFS/GTFS-RT von gtfs.de (DELFI), CC BY-SA 4.0. Bei Weitergabe Quelle nennen und gleiche Lizenz verwenden.
