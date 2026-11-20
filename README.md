# gtfs-rt-recorder

Zeichnet den Stuttgart-Ausschnitt (≈ VVS-Gebiet) des GTFS-RT-Feeds von gtfs.de auf,
als Historie für das Erwartungsmodell in A1 (Big Data Engineering, DHBW).
Hintergrund: Leitstand ADR 0020, 0023, Risiko R15.

## Was passiert

GitHub Actions (`.github/workflows/record.yml`) läuft alle 10 min (der Scheduler verspätet sich oft um einige Minuten):

1. `recorder.static_subset`: prüft per HEAD, ob gtfs.de einen neuen Static-Feed hat. Falls ja: Download (~280 MB),
   Ausschnitt bauen (Haltestellen in der Bounding Box, alle Fahrten, die dort halten, samt kompletter
   `stop_times`, `trips`, `routes`, `calendar*`, `agency`) → `data/static/<version>/`.
2. `recorder.snapshot`: holt den RT-Feed (bundesweit, ~30 MB), behält Trip-Updates und Alerts mit Bezug
   zum Ausschnitt und speichert sie **unverändert als Protobuf** (xz) als Asset im Release `rt-YYYY-MM-DD`
   (Dateiname `HHMMSSZ.pb.xz`, UTC). Nicht in Git, damit das Repo klein bleibt (~0,4–0,6 MB pro Snapshot).
   Gefiltert wird gegen die zwei jüngsten Static-Versionen (Versionswechsel).
3. Upload ins Tages-Release, danach Commit + Push von Index und ggf. Static-Ausschnitt.

Pro Snapshot eine Zeile in `data/index/YYYY-MM-DD.csv`: Rohgröße, Entitäten gesamt/behalten, Feed-Alter usw.
Das ist auch die Datengrundlage für die Volumen-Hochrechnung auf den Gesamtfeed (ADR 0018).

## Warum 10 Minuten

Beendete Fahrten bleiben noch ≥ 60 min nach dem letzten Halt im Feed (Messung 17.11.2026). Rund 4 % der
vergangenen Halte verschwinden aber schon nach wenigen Minuten aus laufenden Fahrten; je kürzer der Takt, desto
öfter ist für diese Halte die Ist-Zeit statt nur der letzten Prognose erfasst. Das Repo ist öffentlich, damit die
Actions-Minuten nicht begrenzt sind (privat wären auf GitHub Free nur ~30 min Takt möglich).

## Auslöser

Der GitHub-Scheduler ist „best effort“ und hat hier in den ersten zwei Tagen nur etwa alle 3–8 h ausgelöst
statt alle 10 min. Deshalb gibt es zusätzliche Auslöser per `workflow_dispatch`; die Concurrency-Gruppe verhindert
überlappende Läufe.

- **Lokal (Notbehelf):** `tools/trigger-local.sh` per launchd alle 10 min, nur solange der Mac wach ist.
  Installation: `__HOME__` in `tools/de.gtfs-rt-recorder.trigger.plist` durch das Home-Verzeichnis ersetzen, nach
  `~/Library/LaunchAgents/` kopieren, `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/de.gtfs-rt-recorder.trigger.plist`.
  Entfernen: `launchctl bootout gui/$(id -u)/de.gtfs-rt-recorder.trigger`. Log: `~/Library/Logs/gtfs-rt-recorder-trigger.log`.
- **Extern (Hauptweg, seit 20.11.2026):** cron-job.org ruft alle 10 min
  `POST https://api.github.com/repos/FabianGlueck/gtfs-rt-recorder/actions/workflows/record.yml/dispatches`
  mit Body `{"ref":"main"}` auf, Fine-grained-Token nur für dieses Repo (Actions: Read and write), gültig bis 18.02.2027.

## Replay

```bash
gh release download rt-2026-11-18 -D data/rt/2026-11-18          # ein Tag
for t in $(gh release list -L 200 --json tagName -q '.[].tagName'); do gh release download $t -D data/rt/${t#rt-} --skip-existing; done
```

```python
import lzma
from google.transit import gtfs_realtime_pb2 as pb
f = pb.FeedMessage()
f.ParseFromString(lzma.decompress(open("data/rt/2026-11-18/081100Z.pb.xz", "rb").read()))
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
