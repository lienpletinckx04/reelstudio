#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  Studio starten.command — dubbelklik dit bestand om de studio te openen.
#
#  Doet ook het werk eromheen: rechten goedzetten (die gaan verloren als je
#  de map als zip downloadt), en controleren of ffmpeg overlays kan tekenen.
#  Kan dat niet, dan biedt hij aan om het meteen te repareren — je hoeft
#  dus geen commando's over te typen.
#
#  Opent dit bestand in een teksteditor in plaats van in Terminal? Dan mist
#  het "mag uitvoeren"-vinkje. Rechtsklik → Toon info → Openen met: Terminal
#  → Alles wijzigen. Of open Terminal en typ:  ./reelstudio.sh studio
# ══════════════════════════════════════════════════════════════════
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
chmod +x reelstudio.sh herstel.sh installeer.sh "Studio starten.command" 2>/dev/null

echo "Reelstudio studio starten …"
echo

# Kan deze ffmpeg overlays tekenen? Zo niet: aanbieden het te repareren,
# want anders opent de studio wel maar mislukt elke render.
if ! python3 -c "
import sys, omgeving
ff, _ = omgeving.zoek_ffmpeg()
sys.exit(0 if ff and omgeving.mogelijkheden(ff)['ass'] else 1)
" 2>/dev/null; then
  echo "Deze computer kan nog geen overlays tekenen (ondertitels, kaarten)."
  printf "Nu repareren? [J/n] "
  read -r antwoord
  case "$antwoord" in
    [nN]*) echo "Overgeslagen — de studio gaat open, renderen lukt nog niet." ;;
    *) ./herstel.sh ;;
  esac
  echo
fi

echo "(dit venster mag je laten staan; sluiten stopt de studio)"
echo
./reelstudio.sh studio
echo
read -n 1 -s -r -p "Studio gestopt. Druk op een toets om dit venster te sluiten…"
