#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  herstel.sh — repareert een ffmpeg die geen overlays kan tekenen.
#
#      ./herstel.sh
#
#  "deze ffmpeg is gebouwd zonder libass" is de meest voorkomende reden
#  dat de tool niet wil renderen. Er is niet één oplossing die overal
#  werkt: het hangt af van welke ffmpeg er staat en waar hij vandaan
#  komt. Dit script probeert de manieren op volgorde van snelheid, test
#  na élke stap of het écht werkt, en stopt zodra het lukt.
#
#  Het compileert niets tenzij het niet anders kan, en zegt dat dan
#  eerst — een bronbouw duurt een half uur.
# ══════════════════════════════════════════════════════════════════
set -u
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HIER" || exit 1

zeg()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
nok()  { printf "  ✗ %s\n" "$*"; }
info() { printf "    %s\n" "$*"; }

# Welke ffmpeg gebruikt de tool zélf? Niet "welke staat er in PATH" — er kan
# een pad in instellingen.yaml staan, en dan repareren we anders de verkeerde.
huidige_ffmpeg() {
  python3 - <<'PY' 2>/dev/null
import omgeving
ff, _ = omgeving.zoek_ffmpeg()
print(ff or "")
PY
}

# De enige eerlijke test: kan hij ondertitels tekenen? Niet "staat libass in de
# configuratie", maar één echt beeldje renderen met het ass-filter erop.
kan_overlays() {
  local ff="$1"
  [ -n "$ff" ] || return 1
  "$ff" -hide_banner -filters 2>/dev/null | grep -q " ass " || return 1
  local proef="$(mktemp -d)/proef.ass"
  cat > "$proef" <<'ASS'
[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Alignment, MarginV
Style: S,Sans,30,&H00FFFFFF,5,0
[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:01.00,S,test
ASS
  "$ff" -hide_banner -loglevel error -f lavfi -i color=black:s=320x240:d=0.1 \
        -vf "ass=$proef" -frames:v 1 -f null - >/dev/null 2>&1
}

# Na elke installatie moet de gemeten-eigenschappen-cache weg, anders blijft de
# tool het oude antwoord geloven.
opnieuw_meten() { rm -f .machine_cache.json; }

FF="$(huidige_ffmpeg)"
zeg "Nakijken"
if [ -n "$FF" ]; then
  info "ffmpeg: $FF"
else
  nok "geen ffmpeg gevonden"
fi

if kan_overlays "$FF"; then
  ok "overlays werken al — er valt niets te repareren"
  opnieuw_meten
  zeg "Klaar"
  echo "  Start de studio met:  ./reelstudio.sh studio"
  exit 0
fi
nok "deze ffmpeg kan geen overlays tekenen"

case "$(uname -s)" in
  Darwin) SYSTEEM=mac ;;
  Linux)  SYSTEEM=linux ;;
  *)      echo "Op Windows: zie LEESMIJ.md"; exit 1 ;;
esac

probeer() {   # probeer "<uitleg>" <commando…>
  local uitleg="$1"; shift
  zeg "$uitleg"
  "$@"
  FF="$(huidige_ffmpeg)"
  if kan_overlays "$FF"; then
    opnieuw_meten
    zeg "Gelukt"
    echo "  Overlays werken nu. Start de studio met:"
    echo "      ./reelstudio.sh studio"
    exit 0
  fi
  nok "nog niet gelukt — volgende manier proberen"
}

if [ "$SYSTEEM" = mac ]; then
  BREW="$(command -v brew || true)"
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -n "$BREW" ] && break
    [ -x "$b" ] && BREW="$b"
  done
  if [ -z "$BREW" ]; then
    nok "geen Homebrew — dat is nodig om ffmpeg te installeren"
    info "Plak deze regel in Terminal, en draai daarna ./herstel.sh opnieuw:"
    info '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
  fi

  # 1. libass ontbrak misschien tóén ffmpeg gebouwd werd. Eerst libass
  #    installeren en ffmpeg opnieuw ophalen is verreweg het snelst.
  probeer "Manier 1 — libass installeren en ffmpeg opnieuw ophalen" \
    bash -c "'$BREW' install libass && '$BREW' reinstall ffmpeg"

  # 2. De aparte ffmpeg-tap levert kant-en-klare builds mét libass. Twee
  #    formules met dezelfde naam kunnen niet naast elkaar staan, dus de
  #    versie uit homebrew/core moet eerst weg. Lukt de nieuwe dan toch niet,
  #    dan zetten we de oude terug — je mag niet zonder ffmpeg achterblijven.
  tap_ffmpeg() {
    "$BREW" tap homebrew-ffmpeg/ffmpeg || return 1
    "$BREW" uninstall --ignore-dependencies ffmpeg 2>/dev/null
    if ! "$BREW" install homebrew-ffmpeg/ffmpeg/ffmpeg; then
      info "mislukt — de vorige ffmpeg wordt teruggezet"
      "$BREW" install ffmpeg
      return 1
    fi
  }
  probeer "Manier 2 — de ffmpeg uit de ffmpeg-tap (mét libass)" tap_ffmpeg

  # 3. Dezelfde formule, maar zelf gebouwd met libass expliciet aangezet.
  #    Traag, dus eerst vragen. `ffmpeg-full` bestaat niet in deze tap —
  #    het is één formule met opties.
  zeg "Manier 3 — ffmpeg zelf bouwen met libass"
  info "Dit compileert ffmpeg vanaf de broncode en duurt 15 tot 30 minuten."
  printf "    Nu doen? [j/N] "
  read -r antwoord
  case "$antwoord" in
    [jJyY]*)
      bouw_ffmpeg() {
        "$BREW" tap homebrew-ffmpeg/ffmpeg || return 1
        "$BREW" uninstall --ignore-dependencies ffmpeg 2>/dev/null
        "$BREW" install --build-from-source homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass \
          || { info "mislukt — de vorige ffmpeg wordt teruggezet"; "$BREW" install ffmpeg; return 1; }
      }
      probeer "Bouwen" bouw_ffmpeg ;;
    *) info "overgeslagen" ;;
  esac
else
  if command -v apt-get >/dev/null 2>&1; then
    probeer "Manier 1 — ffmpeg uit apt" \
      bash -c "sudo apt-get update -qq && sudo apt-get install -y ffmpeg libass9"
  elif command -v dnf >/dev/null 2>&1; then
    probeer "Manier 1 — ffmpeg uit dnf" sudo dnf install -y ffmpeg libass
  elif command -v pacman >/dev/null 2>&1; then
    probeer "Manier 1 — ffmpeg uit pacman" sudo pacman -S --noconfirm ffmpeg libass
  fi
fi

zeg "Niet gelukt"
cat <<EOF
  Geen van de manieren leverde een ffmpeg op die overlays kan tekenen.
  Stuur dit door, dan is het meteen duidelijk waar het misgaat:

      $FF -version | head -3

  Ondertussen werkt de studio wel: je kunt video's invoegen en aanwijzen,
  alleen renderen lukt nog niet.
EOF
exit 1
