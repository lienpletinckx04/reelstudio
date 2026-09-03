#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  reelstudio.sh — van opname naar afgewerkte reel of tutorial
#
#  Eerste keer:
#    ./installeer.sh                                  # zet alles klaar
#    ./reelstudio.sh dokter                             # wat staat er klaar?
#    ./reelstudio.sh proef                              # testrender, bewijst het
#
#  Je eigen huisstijl:
#    ./reelstudio.sh merk nieuw mijnmerk                # vraag voor vraag
#    ./reelstudio.sh merk toon  mijnmerk                # voorbeeldbeeld
#
#  Een les maken:
#    ./reelstudio.sh nieuw  les2-website ~/Downloads/opname.mp4 --titel "Je website bouwen"
#    ./reelstudio.sh frame  les2-website 1:05 --raster  # beeld met coördinaten
#    ./reelstudio.sh check  les2-website                # storyboard nakijken
#    ./reelstudio.sh render les2-website --preview      # snel
#    ./reelstudio.sh render les2-website                # definitief
#
#  Op Windows: gebruik reelstudio.ps1 in plaats van dit bestand.
#  Zie LEESMIJ.md
# ══════════════════════════════════════════════════════════════════
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 niet gevonden. Draai eerst ./installeer.sh" >&2
  exit 1
fi
exec python3 "$HIER/reelstudio.py" "$@"
