#!/usr/bin/env python3
"""
omgeving.py — alles wat van de computer afhangt, op één plek.

Reelstudio moet op een Mac, een Windows-pc en een Linux-machine draaien.
De verschillen tussen die drie (waar staat ffmpeg, welke video-encoder is er,
waar staan de fonts, hoe installeer je whisper) horen niet verspreid door de
rest van de code te zitten — ze staan hier.

Elke functie geeft óf een bruikbaar antwoord, óf None plus een hint die aan
de gebruiker getoond kan worden. Niets in dit bestand stopt het programma;
dat beslist de aanroeper.
"""
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ── welk systeem draaien we ────────────────────────────────────────
_s = platform.system().lower()
SYSTEEM = "mac" if _s == "darwin" else ("windows" if _s == "windows" else "linux")
IS_MAC = SYSTEEM == "mac"
IS_WINDOWS = SYSTEEM == "windows"
SYSTEEM_NAAM = {"mac": "macOS", "windows": "Windows", "linux": "Linux"}[SYSTEEM]


# ═══════════════════════════════════════════════════════════════════
#  Instellingen (optioneel bestand, voor persoonlijke paden)
# ═══════════════════════════════════════════════════════════════════
_INSTELLINGEN = None


def instellingen():
    """Leest instellingen.yaml naast dit bestand (mag ontbreken).

    Bedoeld voor dingen die per computer verschillen en niet in git horen:
    een eigen whisper-modelpad, een eigen standaardmerk, een eigen
    woordenlijst voor de transcriptie.
    """
    global _INSTELLINGEN
    if _INSTELLINGEN is None:
        _INSTELLINGEN = {}
        pad = os.path.join(HERE, "instellingen.yaml")
        if os.path.exists(pad):
            try:
                sys.path.insert(0, HERE)
                from miniyaml import load as yload
                _INSTELLINGEN = yload(pad) or {}
            except Exception as e:
                print(f"  ! instellingen.yaml kon niet gelezen worden: {e}", file=sys.stderr)
    return _INSTELLINGEN


def instelling(naam, standaard=None):
    """Eén instelling: eerst omgevingsvariabele, dan instellingen.yaml."""
    env = (os.environ.get("REELSTUDIO_" + naam.upper())
           or os.environ.get("TUTORIAL_" + naam.upper()))   # oude naam blijft werken
    if env:
        return env
    v = instellingen().get(naam)
    return standaard if v is None else v


# ═══════════════════════════════════════════════════════════════════
#  Programma's zoeken
# ═══════════════════════════════════════════════════════════════════
# Plekken waar een pakketbeheerder ffmpeg neerzet en die niet altijd in PATH
# staan — vooral bij Windows-installaties en bij homebrew op een Mac waar de
# terminal via een ander profiel opstart.
_EXTRA_PADEN = {
    "mac": [
        "/opt/homebrew/opt/ffmpeg-full/bin",   # brew install ffmpeg-full
        "/opt/homebrew/bin",                   # brew op Apple Silicon
        "/usr/local/bin",                      # brew op Intel
        "/opt/local/bin",                      # MacPorts
    ],
    "linux": ["/usr/bin", "/usr/local/bin", "/snap/bin",
              os.path.expanduser("~/.local/bin")],
    "windows": [
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ffmpeg\bin",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        os.path.expandvars(r"%ProgramData%\chocolatey\bin"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\ffmpeg\bin"),
    ],
}


def zoek_programma(naam, extra=()):
    """Zoekt een programma in PATH en op de gebruikelijke installatieplekken."""
    gevonden = shutil.which(naam)
    if gevonden:
        return gevonden
    exts = [".exe", ".bat", ".cmd"] if IS_WINDOWS else [""]
    for map_ in list(extra) + _EXTRA_PADEN.get(SYSTEEM, []):
        if not map_:
            continue
        for ext in exts:
            p = os.path.join(map_, naam + ext)
            if os.path.exists(p):
                return p
    return None


def zoek_ffmpeg():
    """(ffmpeg, ffprobe) — beide None als ffmpeg niet gevonden is."""
    eigen = instelling("ffmpeg")
    if eigen and os.path.exists(eigen):
        map_ = os.path.dirname(eigen)
        return eigen, (zoek_programma("ffprobe", [map_]) or "ffprobe")
    ff = zoek_programma("ffmpeg")
    if not ff:
        return None, None
    # ffprobe hoort naast ffmpeg te staan
    return ff, (zoek_programma("ffprobe", [os.path.dirname(ff)]) or "ffprobe")


def _draai(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


_MOGELIJKHEDEN = {}


def mogelijkheden(ff):
    """Wat kan deze ffmpeg? {'ass': bool, 'encoders': set}. Wordt gecachet."""
    if ff in _MOGELIJKHEDEN:
        return _MOGELIJKHEDEN[ff]
    filters = _draai([ff, "-hide_banner", "-filters"])
    encs = _draai([ff, "-hide_banner", "-encoders"])
    gevonden = set()
    for naam in ("libx264", "h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "libx265"):
        # de encoderlijst zet de naam altijd als los woord in de kolom erna
        if f" {naam} " in encs:
            gevonden.add(naam)
    m = {"ass": " ass " in filters, "encoders": gevonden}
    _MOGELIJKHEDEN[ff] = m
    return m


def _cache_pad():
    return os.path.join(HERE, ".machine_cache.json")


def _cache():
    try:
        import json
        with open(_cache_pad(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _cache_schrijf(d):
    try:
        import json
        with open(_cache_pad(), "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except Exception:
        pass


def werkt_encoder(ff, encoder):
    """Encodeert één testbeeldje om te zien of de encoder écht werkt.

    `ffmpeg -encoders` toont wat er meegecompileerd is, niet wat er op deze
    computer draait: een ffmpeg-build kan h264_nvenc aanbieden op een machine
    zonder NVIDIA-kaart. Dat merk je anders pas als de render halverwege stopt.
    Het antwoord wordt onthouden, dus dit kost één keer een halve seconde.
    """
    c = _cache()
    sleutel = f"enc:{encoder}"
    if sleutel in c:
        return c[sleutel]
    uit = os.devnull
    try:
        r = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=black:s=320x240:d=0.1", "-c:v", encoder,
             "-frames:v", "1", "-f", "null", uit],
            capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
    except Exception:
        ok = False
    c[sleutel] = ok
    _cache_schrijf(c)
    return ok


def kies_encoder(ff, preview=False, bitrate="9M", crf=19):
    """Video-encoder-argumenten die op déze computer echt werken.

    Preview mag snel en lelijk zijn; de eindrender kiest kwaliteit per MB.
    Een hardware-encoder is veel sneller, maar wordt alleen gebruikt nadat
    hij een testbeeldje heeft overleefd.
    """
    kan = mogelijkheden(ff)["encoders"]
    snel = next((e for e in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf")
                 if e in kan and werkt_encoder(ff, e)), None)
    if preview:
        if snel:
            return ["-c:v", snel, "-b:v", "4M", "-profile:v", "high"]
        if "libx264" in kan:
            # ultrafast + hoge crf: een preview hoeft alleen snel te zijn
            return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-pix_fmt", "yuv420p"]
        return ["-c:v", "mpeg4", "-q:v", "4"]
    if "libx264" in kan:
        return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if snel:
        return ["-c:v", snel, "-b:v", str(bitrate), "-profile:v", "high"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


# ═══════════════════════════════════════════════════════════════════
#  Whisper (transcriptie)
# ═══════════════════════════════════════════════════════════════════
MODEL_NAAM = "ggml-large-v3-turbo.bin"
MODEL_URL = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
             + MODEL_NAAM)


def zoek_whisper():
    """whisper-cli van whisper.cpp; heet op sommige installaties nog 'main'."""
    eigen = instelling("whisper")
    if eigen and os.path.exists(eigen):
        return eigen
    return zoek_programma("whisper-cli") or zoek_programma("whisper-cpp")


def model_mappen():
    """Plekken waar het whisper-model mag staan, in volgorde van voorkeur."""
    mappen = [os.path.join(HERE, "models")]
    eigen = instelling("model_map")
    if eigen:
        mappen.insert(0, os.path.expanduser(eigen))
    if IS_MAC:
        mappen.append(os.path.expanduser("~/Library/Application Support/tutorialtool/models"))
    elif IS_WINDOWS:
        mappen.append(os.path.expandvars(r"%LOCALAPPDATA%\tutorialtool\models"))
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        mappen.append(os.path.join(xdg, "tutorialtool", "models"))
    return mappen


def zoek_whisper_model():
    eigen = instelling("model")
    if eigen and os.path.exists(os.path.expanduser(eigen)):
        return os.path.expanduser(eigen)
    for m in model_mappen():
        p = os.path.join(m, MODEL_NAAM)
        if os.path.exists(p):
            return p
    return None


# ═══════════════════════════════════════════════════════════════════
#  Installatiehints — per systeem, letterlijk over te typen
# ═══════════════════════════════════════════════════════════════════
def hint(wat):
    """Eén regel die vertelt hóe je het ontbrekende stuk installeert."""
    h = {
        "ffmpeg": {
            "mac": "brew install ffmpeg",
            "linux": "sudo apt install ffmpeg   (of: sudo dnf install ffmpeg)",
            "windows": "winget install Gyan.FFmpeg   (daarna terminal opnieuw openen)",
        },
        "whisper": {
            "mac": "brew install whisper-cpp",
            "linux": "zie https://github.com/ggml-org/whisper.cpp (zelf bouwen)",
            "windows": "zie https://github.com/ggml-org/whisper.cpp (release downloaden)",
        },
        "model": {
            "mac": f"./installeer.sh   (of het model zelf naar models/{MODEL_NAAM})",
            "linux": f"./installeer.sh   (of het model zelf naar models/{MODEL_NAAM})",
            "windows": f".\\installeer.ps1   (of het model zelf naar models\\{MODEL_NAAM})",
        },
    }
    return h.get(wat, {}).get(SYSTEEM, "")
