#!/bin/bash
# ══════════════════════════════════════════════════════════════════
#  installeer.sh — zet Reelstudio klaar op een Mac of Linux-machine.
#
#      ./installeer.sh
#
#  Installeert wat ontbreekt (ffmpeg met libass, whisper), haalt het
#  transcriptiemodel op, en draait daarna de dokter. Alles wat er al
#  staat blijft staan; het script is veilig om opnieuw te draaien.
#
#  Windows: gebruik installeer.ps1
# ══════════════════════════════════════════════════════════════════
set -u
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HIER" || exit 1

MODEL_NAAM="ggml-large-v3-turbo.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_NAAM"

zeg()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
nok()  { printf "  ✗ %s\n" "$*"; }
info() { printf "    %s\n" "$*"; }

case "$(uname -s)" in
  Darwin) SYSTEEM=mac ;;
  Linux)  SYSTEEM=linux ;;
  *)      echo "Onbekend systeem $(uname -s). Op Windows: gebruik installeer.ps1"; exit 1 ;;
esac

# Op een Mac staat brew in /opt/homebrew/bin (Apple Silicon) of /usr/local/bin
# (Intel). Vlak na het installeren zit dat nog niet in PATH, dus kijken we ook
# rechtstreeks — anders zegt dit script "geen homebrew" terwijl het er wel staat.
vind_brew() {
  command -v brew 2>/dev/null && return 0
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && { echo "$b"; return 0; }
  done
  return 1
}
BREW="$(vind_brew || true)"

zeg "Reelstudio installeren op $SYSTEEM"

# ── 1. Python ─────────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
else
  nok "python3 ontbreekt"
  [ "$SYSTEEM" = mac ] && info "brew install python" || info "sudo apt install python3"
  exit 1
fi

# ── 2. ffmpeg (met libass, anders geen overlays) ──────────────────
heeft_libass() {
  command -v ffmpeg >/dev/null 2>&1 && ffmpeg -hide_banner -filters 2>/dev/null | grep -q " ass "
}

if heeft_libass; then
  ok "ffmpeg met libass"
else
  if command -v ffmpeg >/dev/null 2>&1; then
    nok "ffmpeg staat er, maar zonder libass — overlays werken niet"
  else
    nok "ffmpeg ontbreekt"
  fi
  if [ "$SYSTEEM" = mac ]; then
    if [ -n "$BREW" ]; then
      info "installeren met homebrew …"
      "$BREW" install ffmpeg
    else
      cat <<'HELP'

    Hiervoor is Homebrew nodig — de standaardmanier om dit soort programma's
    op een Mac te installeren. Je hebt het nog niet.

    1. Kopieer deze regel, plak ze in Terminal en druk op Enter:

       /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

       Hij vraagt je wachtwoord (je ziet niets terwijl je typt, dat hoort zo)
       en doet er een paar minuten over.

    2. Zegt Homebrew op het einde dat je nog twee regels moet uitvoeren om hem
       aan je PATH toe te voegen? Doe dat dan.

    3. Sluit Terminal, open een nieuw venster, en draai ./installeer.sh opnieuw.

HELP
      exit 1
    fi
  else
    if command -v apt-get >/dev/null 2>&1; then
      info "installeren met apt …"
      sudo apt-get update -qq && sudo apt-get install -y ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y ffmpeg
    elif command -v pacman >/dev/null 2>&1; then
      sudo pacman -S --noconfirm ffmpeg
    else
      info "installeer ffmpeg met de pakketbeheerder van je distributie"
      exit 1
    fi
  fi
  heeft_libass && ok "ffmpeg met libass" || { nok "ffmpeg werkt nog niet — zie hierboven"; exit 1; }
fi

# ── 3. whisper (optioneel: je kunt ondertitels ook zelf schrijven) ──
if command -v whisper-cli >/dev/null 2>&1 || command -v whisper-cpp >/dev/null 2>&1; then
  ok "whisper-cli"
else
  nok "whisper-cli ontbreekt — nodig om automatisch te transcriberen"
  if [ "$SYSTEEM" = mac ] && [ -n "$BREW" ]; then
    info "installeren met homebrew …"
    "$BREW" install whisper-cpp || info "niet gelukt — je kunt ondertitels ook zelf schrijven"
  else
    info "bouw het zelf: https://github.com/ggml-org/whisper.cpp"
    info "(zonder whisper werkt alles behalve automatisch transcriberen)"
  fi
fi

# ── 4. transcriptiemodel (±1,5 GB) ────────────────────────────────
mkdir -p models
if [ -f "models/$MODEL_NAAM" ]; then
  ok "transcriptiemodel staat klaar"
else
  nok "transcriptiemodel ontbreekt (±1,5 GB)"
  printf "    Nu downloaden? [j/N] "
  read -r antwoord
  case "$antwoord" in
    [jJyY]*)
      # -C - hervat een afgebroken download i.p.v. opnieuw te beginnen
      curl -L -C - -o "models/$MODEL_NAAM" "$MODEL_URL" \
        && ok "model opgehaald" \
        || { nok "download mislukt — probeer opnieuw, hij hervat vanzelf"; }
      ;;
    *) info "later: curl -L -o models/$MODEL_NAAM $MODEL_URL" ;;
  esac
fi

# ── 5. eigen instellingen ─────────────────────────────────────────
if [ ! -f instellingen.yaml ] && [ -f instellingen_voorbeeld.yaml ]; then
  cp instellingen_voorbeeld.yaml instellingen.yaml
  ok "instellingen.yaml aangemaakt (persoonlijk, gaat niet mee in git)"
fi

chmod +x reelstudio.sh "Studio starten.command" 2>/dev/null

# ── 6. nakijken ───────────────────────────────────────────────────
zeg "Nakijken"
python3 reelstudio.py dokter || exit 1

zeg "Klaar"
cat <<'EOF'
  De studio openen (geen terminal nodig): dubbelklik in Finder op
      Studio starten.command

  Of vanaf hier bewijzen dat alles samenwerkt met een testrender:

      ./reelstudio.sh proef

  Daarna je eigen opname — via de studio, of:

      ./reelstudio.sh nieuw mijn-les ~/pad/naar/opname.mp4 --titel "Mijn eerste les"

  En je eigen huisstijl:

      ./reelstudio.sh merk nieuw mijnmerk
EOF
