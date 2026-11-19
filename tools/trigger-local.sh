#!/bin/bash
# Notbehelf, solange der GitHub-Scheduler unzuverlässig ist: stößt den Recorder per workflow_dispatch an.
# Wird von launchd alle 10 min aufgerufen (tools/de.gtfs-rt-recorder.trigger.plist), nur solange der Mac wach ist.
set -u
LOG="$HOME/Library/Logs/gtfs-rt-recorder-trigger.log"
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if out=$(/opt/homebrew/bin/gh workflow run record.yml -R FabianGlueck/gtfs-rt-recorder 2>&1); then
  echo "$ts ok" >> "$LOG"
else
  echo "$ts FEHLER: $out" >> "$LOG"
fi
# Log klein halten
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
