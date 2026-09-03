#!/usr/bin/env python3
"""
tutorial.py — van schermopname naar afgewerkte tutorial-video.

Leest een storyboard (storyboard.yaml) + ondertitels (srt) en rendert met
ffmpeg één video met:
  • intro- en outro-kaart in de merkstijl
  • ondertitels in een afgeronde pil
  • stap-kaarten ("Stap 2 van 8 — Kies je model") + klein stap-chipje
  • highlights: spotlight + rand + label rond een stuk scherm, optioneel met zoom
  • tip- en prompt-kaarten rechtsboven
  • knippen en versnellen van stukken ("Claude werkt…")

Alle overlays worden als één ASS-bestand getekend door libass — één
renderpass, geen extra bibliotheken. Zie LEESMIJ.md voor het storyboard.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import omgeving  # noqa: E402
from miniyaml import load as yload, YamlFout  # noqa: E402
from fontmetrics import haal_font  # noqa: E402

W, H, FPS = 1920, 1080, 30          # standaardformaat (liggend)
BRON_W, BRON_H = 1920, 1080         # de ruimte waarin storyboard-coördinaten staan

# ── uitvoerformaten ───────────────────────────────────────────────
# `veilig_*` is de rand die de app van het platform zelf overtekent. Op
# Instagram staan onderaan de gebruikersnaam, het bijschrift en de audio, en
# rechts de knoppen voor liken en delen. Kaarten en ondertitels blijven daar
# weg, anders staat je tekst onder een knop.
FORMATEN = {
    # `tekst_schaal` staat los van de beeldmaat, en dat is met opzet. In een
    # reel is het beeld kleiner (een strook in een staand kader) maar moet de
    # tekst juist gróter: hij wordt op een telefoon gelezen, vaak zonder geluid.
    # Alles even hard meeschalen zou de ondertitels onleesbaar maken.
    "liggend":  {"breedte": 1920, "hoogte": 1080,
                 "veilig_boven": 0, "veilig_onder": 0, "veilig_rechts": 0,
                 "marge": 40, "tekst_schaal": 1.0, "titelbreedte": 1560,
                 "ondertitelbreedte": 1100, "kaart_schaal": 1.0,
                 "intro_duur": 5, "outro_duur": 6.5},
    "reel":     {"breedte": 1080, "hoogte": 1920,
                 "veilig_boven": 150, "veilig_onder": 430, "veilig_rechts": 210,
                 "marge": 44, "tekst_schaal": 1.5, "titelbreedte": 968,
                 "ondertitelbreedte": 940, "kaart_schaal": 1.15,
                 "intro_duur": 1.6, "outro_duur": 3.2},
    "vierkant": {"breedte": 1080, "hoogte": 1080,
                 "veilig_boven": 0, "veilig_onder": 0, "veilig_rechts": 0,
                 "marge": 40, "tekst_schaal": 1.2, "titelbreedte": 900,
                 "ondertitelbreedte": 940, "kaart_schaal": 1.1,
                 "intro_duur": 3, "outro_duur": 4},
}
RAMP = 0.6          # zoom in/uit-tijd in seconden
STANDAARD_MERK = str(omgeving.instelling("merk", "standaard"))

# Waar een merkbestand geen font opgeeft: een keten die op macOS, Windows én
# Linux op een echt lettertype uitkomt. Eerst de mooiste, dan wat er altijd is.
_ZWAAR = "Helvetica Neue Bold | Arial Bold | Segoe UI Bold | Liberation Sans Bold | DejaVu Sans Bold"
_MIDDEN = "Helvetica Neue Medium | Segoe UI Semibold | Arial Bold | Liberation Sans Bold | DejaVu Sans Bold"
_GEWOON = "Helvetica Neue | Arial | Segoe UI | Liberation Sans | DejaVu Sans"
STANDAARD_FONTS = {"titel": _ZWAAR, "kop": _ZWAAR, "label": _MIDDEN,
                   "tekst": _GEWOON, "ondertitel": _MIDDEN}


# ═══════════════════════════════════════════════════════════════════
#  Merken
# ═══════════════════════════════════════════════════════════════════
# Wat een merkbestand niet zegt, wordt hier ingevuld. Zo blijft een eigen
# merkbestand kort en leesbaar: je zet erin wat jóu onderscheidt (kleuren,
# naam, lettertype) en de rest volgt vanzelf.
MERK_STANDAARDWAARDEN = {
    "stijl": "editorial",
    "wit": "#ffffff",
    "kop_spatie": -0.02, "eyebrow_caps": True, "eyebrow_spatie": 0.06,
    "radius_knop": 10, "radius_kaart": 16, "kaart_schaduw": False, "kaart_rand": "lijn",
    "ondertitel_em": 36, "ondertitel_tekst": "creme", "ondertitel_pil": "ink",
    "ondertitel_pil_alpha": 0.92, "ondertitel_onderrand": 40, "ondertitel_max_regels": 2,
    "highlight_kleur": "accent", "dim_kleur": "ink", "dim_sterkte": 0.34,
    "kaart_achtergrond": "wit", "kaart_alpha": 0.97, "kaart_tekst": "ink",
    "kaart_eyebrow": "accent", "kaart_subtekst": "grijs",
    "chip_achtergrond": "ink", "chip_tekst": "creme",
    "intro_duur": 5, "outro_duur": 6.5,
    "intro_achtergrond": "creme", "outro_achtergrond": "ink",
    "band_achtergrond": "ink", "band_tekstkleur": "creme",
    "outro_band_achtergrond": "accent", "outro_band_tekstkleur": "wit",
}


def is_donker(hx):
    """Is deze kleur donker genoeg om er lichte tekst op te zetten?"""
    hx = str(hx).lstrip("#")
    if len(hx) != 6:
        return True
    r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


def is_hex(v):
    return isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip()) is not None


def meng(a, b, deel):
    """Kleur a naar b toe schuiven; deel 0 = a, 1 = b."""
    a, b = a.lstrip("#"), b.lstrip("#")
    uit = []
    for i in (0, 2, 4):
        va, vb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        uit.append(int(round(va + (vb - va) * deel)))
    return "#{:02x}{:02x}{:02x}".format(*uit)


def hexwaarde(merk, sleutel, standaard):
    """De hexkleur achter een sleutel, ook als die naar een andere wijst.

    Een merkbestand mag  accent: roze  schrijven en elders  roze: "#f2295b".
    Voor het afleiden van grijstinten hebben we de echte kleur nodig.
    """
    v = merk.get(sleutel)
    for _ in range(4):                      # ketting van verwijzingen volgen
        if is_hex(v):
            return v.strip().lower()
        if isinstance(v, str) and v in merk:
            v = merk[v]
        else:
            break
    return standaard


def merkpad(naam):
    return os.path.join(HERE, "merk", f"{naam}.yaml")


def laad_merk(naam):
    """Merkbestand met alle standaardwaarden erbij.

    Kleuren die je niet noemt worden afgeleid van de drie die je wél geeft:
    een grijs tussen tekst en achtergrond, een gedempt grijs daarboven, een
    dun lijntje net donkerder dan de achtergrond. Zo kan een merkbestand uit
    vijf regels bestaan en toch overal kloppen.
    """
    pad = merkpad(naam)
    if not os.path.exists(pad):
        beschikbaar = sorted(f[:-5] for f in os.listdir(os.path.join(HERE, "merk"))
                             if f.endswith(".yaml"))
        die(f"merkbestand '{naam}' bestaat niet ({pad}).\n"
            f"  Beschikbaar: {', '.join(beschikbaar)}\n"
            f"  Nieuw merk maken:  ./reelstudio.sh merk nieuw {naam}")
    m = yload(pad) or {}
    creme = hexwaarde(m, "creme", "#f7f5f2")
    ink = hexwaarde(m, "ink", "#1f2328")
    accent = hexwaarde(m, "accent", "#2f6df6")
    afgeleid = {
        "creme": creme, "ink": ink, "accent": accent,
        "grijs": meng(ink, creme, 0.35),          # bodytekst: zachter dan een kop
        "muted": meng(ink, creme, 0.55),          # bijschriften
        "lijn": meng(creme, ink, 0.12),           # nauwelijks zichtbaar randje
        "perzik": meng(accent, "#ffffff", 0.85),  # tekst op een accentvlak
        "muted_donker": meng(ink, "#ffffff", 0.6),
        "naam": naam,
    }
    uit = dict(MERK_STANDAARDWAARDEN)
    uit.update(afgeleid)
    uit.update({k: v for k, v in m.items() if v is not None})
    # een merk dat 'accent: roze' schrijft houdt die verwijzing; kleur() lost
    # ze op. Alleen als de verwijzing nergens heen leidt vullen we hem aan.
    for sleutel, waarde in (("creme", creme), ("ink", ink), ("accent", accent)):
        if not is_hex(uit.get(sleutel)) and uit.get(sleutel) not in uit:
            uit[sleutel] = waarde
    return uit


# ═══════════════════════════════════════════════════════════════════
#  Hulpjes
# ═══════════════════════════════════════════════════════════════════
FF, FFPROBE = omgeving.zoek_ffmpeg()


def eis_ffmpeg(overlays=True):
    """Zonder ffmpeg kan niets — leg meteen uit hoe je het installeert.

    Overlays zijn een aparte eis: een ffmpeg zonder libass kan wél knippen en
    monteren, alleen geen ondertitels of kaarten tekenen. De studio mag dus
    gewoon opengaan (`overlays=False`) — je kunt kijken, video's invoegen en
    aanwijzen; pas bij het renderen loop je vast. Dat is beter dan een lege
    terminal waar niets opent.
    """
    if not FF:
        die("ffmpeg niet gevonden.\n"
            f"  Installeer het met:  {omgeving.hint('ffmpeg')}\n"
            "  Staat het al op je computer maar niet in PATH? Zet het volledige pad in\n"
            "  instellingen.yaml als  ffmpeg: /pad/naar/ffmpeg")
    if overlays and not omgeving.mogelijkheden(FF)["ass"]:
        die(GEEN_LIBASS)


#  Commando's die daadwerkelijk ondertitels of kaarten op het beeld zetten.
#  De rest (nieuw, studio, frame, merk lijst) komt met elke ffmpeg toe.
TEKENT_OVERLAYS = {"render", "check", "proef", "reel", "merk", "broll"}

GEEN_LIBASS = (
    "deze ffmpeg kan geen overlays tekenen (gebouwd zonder libass).\n"
    "  Zonder libass geen ondertitels, stapkaarten of tips.\n\n"
    "  Repareren:   ./herstel.sh\n"
    "  Dat probeert vanzelf de manieren die werken, en zegt welke gelukt is.")


def die(msg):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def ptime(v):
    """'1:03', '1:03.5', '0:01:03', 63, '63.5' → seconden (float)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        t = 0.0
        for p in parts:
            t = t * 60 + p
        return t
    return float(s)


def ftime(t):
    """seconden → 'm:ss.s' voor meldingen."""
    m = int(t // 60)
    return f"{m}:{t - 60 * m:04.1f}"


def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def hex2ass(hx, alpha=0.0):
    """'#rrggbb' → '&HAABBGGRR' (alpha 0 = dekkend, 1 = onzichtbaar)."""
    hx = hx.lstrip("#")
    r, g, b = hx[0:2], hx[2:4], hx[4:6]
    a = int(round(255 * min(max(alpha, 0.0), 1.0)))
    return f"&H{a:02X}{b}{g}{r}"


def a_tag(alpha):
    """alpha 0..1 (0 = dekkend) → '&HXX&' voor \\1a enz."""
    return f"&H{int(round(255 * min(max(alpha, 0), 1))):02X}&"


def esc(text):
    return str(text).replace("{", "(").replace("}", ")").replace("\\", "/")


def probe_duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def heeft_beeld(path):
    """Zit er beeld in dit bestand, of alleen geluid?

    Een .mp3 of .m4a glipt er anders doorheen: probe_size valt stilzwijgend
    terug op het standaardformaat, en je merkt pas bij het renderen dat er
    niets te zien is. Beter meteen zeggen.
    """
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return out.startswith("video")


def probe_size(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except Exception:
        return W, H


def heeft_audio(path):
    """Heeft dit bestand een geluidsspoor?

    Schermopnames zonder microfoon hebben dat vaak niet. Bij het aan elkaar
    plakken van clips moeten we daar stilte voor in de plaats zetten, anders
    weigert ffmpeg de montage.
    """
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


def normaliseer_vf(creme_hex="#fff8f2"):
    """Bron naar de bronruimte: passend in 1920x1080, zonder vervorming.

    Dit is de ruimte waarin storyboard-coördinaten staan. `frame --raster`
    toont precies deze ruimte, zodat een gebied dat je daar afleest klopt —
    of je de les nu liggend rendert of als reel. Waar dat beeld ín het
    uitvoerkader terechtkomt regelt de klasse Kader.
    """
    c = "0x" + creme_hex.lstrip("#")
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={c},setsar=1")


# ═══════════════════════════════════════════════════════════════════
#  ASS-tekenhulpjes (vectorvormen)
# ═══════════════════════════════════════════════════════════════════
K = 0.5523  # bezier-constante voor kwartcirkels


def rrect(x, y, w, h, r):
    """Afgeronde rechthoek als ASS-drawing (klokwijs)."""
    r = max(0, min(r, w / 2, h / 2))
    k = K * r
    f = lambda v: f"{v:.1f}"
    return (f"m {f(x+r)} {f(y)} "
            f"l {f(x+w-r)} {f(y)} b {f(x+w-r+k)} {f(y)} {f(x+w)} {f(y+r-k)} {f(x+w)} {f(y+r)} "
            f"l {f(x+w)} {f(y+h-r)} b {f(x+w)} {f(y+h-r+k)} {f(x+w-r+k)} {f(y+h)} {f(x+w-r)} {f(y+h)} "
            f"l {f(x+r)} {f(y+h)} b {f(x+r-k)} {f(y+h)} {f(x)} {f(y+h-r+k)} {f(x)} {f(y+h-r)} "
            f"l {f(x)} {f(y+r)} b {f(x)} {f(y+r-k)} {f(x+r-k)} {f(y)} {f(x+r)} {f(y)}")


def rrect_ccw(x, y, w, h, r):
    """Zelfde, tegenwijzerzin (voor een gat in een vorm)."""
    r = max(0, min(r, w / 2, h / 2))
    k = K * r
    f = lambda v: f"{v:.1f}"
    return (f"m {f(x+r)} {f(y)} "
            f"b {f(x+r-k)} {f(y)} {f(x)} {f(y+r-k)} {f(x)} {f(y+r)} "
            f"l {f(x)} {f(y+h-r)} b {f(x)} {f(y+h-r+k)} {f(x+r-k)} {f(y+h)} {f(x+r)} {f(y+h)} "
            f"l {f(x+w-r)} {f(y+h)} b {f(x+w-r+k)} {f(y+h)} {f(x+w)} {f(y+h-r+k)} {f(x+w)} {f(y+h-r)} "
            f"l {f(x+w)} {f(y+r)} b {f(x+w)} {f(y+r-k)} {f(x+w-r+k)} {f(y)} {f(x+w-r)} {f(y)}")


def ring(x, y, w, h, r, t):
    """Afgeronde rechthoekige rand met dikte t."""
    return rrect(x, y, w, h, r) + " " + rrect_ccw(x + t, y + t, w - 2 * t, h - 2 * t, max(0, r - t))


def triangle(x, y, size, richting):
    """Klein wijzertje. richting: 'boven' (punt naar boven) of 'onder'."""
    f = lambda v: f"{v:.1f}"
    if richting == "boven":
        return f"m {f(x-size)} {f(y+size)} l {f(x)} {f(y)} l {f(x+size)} {f(y+size)}"
    return f"m {f(x-size)} {f(y-size)} l {f(x)} {f(y)} l {f(x+size)} {f(y-size)}"


# ═══════════════════════════════════════════════════════════════════
#  Tijdlijn: bron-tijd → uitvoer-tijd (knippen + versnellen)
# ═══════════════════════════════════════════════════════════════════
class Tijdlijn:
    def __init__(self, duur, knips, versnels, venster=None):
        self.duur = duur
        lo, hi = (0.0, duur) if not venster else (max(0.0, venster[0]), min(duur, venster[1]))
        self.lo, self.hi = lo, hi
        grens = {lo, hi}
        for a, b in knips:
            grens.update([min(max(a, lo), hi), min(max(b, lo), hi)])
        for a, b, _ in versnels:
            grens.update([min(max(a, lo), hi), min(max(b, lo), hi)])
        pts = sorted(grens)
        segs = []
        for a, b in zip(pts, pts[1:]):
            if b - a < 1e-6:
                continue
            mid = (a + b) / 2
            if any(ka <= mid < kb for ka, kb in knips):
                continue
            speed = 1.0
            for va, vb, f in versnels:
                if va <= mid < vb:
                    speed = float(f)
            if segs and abs(segs[-1][1] - a) < 1e-6 and segs[-1][2] == speed:
                segs[-1] = (segs[-1][0], b, speed)
            else:
                segs.append((a, b, speed))
        self.segs = segs
        self.offs = []
        o = 0.0
        for a, b, f in segs:
            self.offs.append(o)
            o += (b - a) / f
        self.totaal = o

    def out(self, t):
        """bron-seconde → uitvoer-seconde (binnen het lichaam, zonder intro)."""
        if t <= self.lo:
            return 0.0
        for (a, b, f), o in zip(self.segs, self.offs):
            if t < a:
                return o            # in een geknipt stuk → plak aan begin volgend segment
            if t <= b:
                return o + (t - a) / f
        return self.totaal

    def versnelde_stukken(self):
        return [(o, o + (b - a) / f, f) for (a, b, f), o in zip(self.segs, self.offs) if f != 1.0]


# ═══════════════════════════════════════════════════════════════════
#  Ondertitels
# ═══════════════════════════════════════════════════════════════════
def read_srt(path):
    txt = open(path, encoding="utf-8-sig").read().strip().replace("\r", "")
    cues = []
    for blk in re.split(r"\n\s*\n", txt):
        lines = [l for l in blk.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        i = 0
        if re.match(r"^\d+$", lines[0].strip()):
            i = 1
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[i])
        if not m:
            continue
        g = [int(v) for v in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(l.strip() for l in lines[i + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            cues.append([a, b, re.sub(r"\s+", " ", text)])
    return cues


def apply_woordenboek(text, rules):
    for pat, rep in rules:
        text = pat.sub(rep, text)
    return text


def load_woordenboek(path):
    rules = []
    if not os.path.exists(path):
        return rules
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#") or "=>" not in line:
            continue
        a, b = [p.strip() for p in line.split("=>", 1)]
        flags = 0
        if a.startswith("i:"):
            a = a[2:].strip()
            flags = re.IGNORECASE
        rules.append((re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", flags), b))
    return rules


def kort_af(tekst, font, size, maxw):
    """Tekst inkorten tot ze past, met een echt beletselteken."""
    if font.width(tekst, size) <= maxw:
        return tekst
    while tekst and font.width(tekst + "…", size) > maxw:
        tekst = tekst[:-1]
    return tekst.rstrip() + "…"


def wrap(text, font, size, maxw):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if cur and font.width(probe, size) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = probe
    if cur:
        lines.append(cur)
    return lines


def wrap_balanced(text, font, size, maxw):
    """Zoals wrap(), maar met gebalanceerde regels voor koppen. Een '|' in de
    tekst forceert een regelafbreking."""
    if "|" in text:
        out = []
        for deel in text.split("|"):
            out.extend(wrap(deel.strip(), font, size, maxw))
        return out
    lines = wrap(text, font, size, maxw)
    if len(lines) < 2:
        return lines
    words = text.split()
    n = len(lines)
    best, best_score = lines, max(font.width(l, size) for l in lines)
    # probeer alle verdelingen over n regels (n klein) en kies de smalste max-breedte
    import itertools
    cuts = range(1, len(words))
    for combo in itertools.combinations(cuts, n - 1):
        idx = (0,) + combo + (len(words),)
        cand = [" ".join(words[idx[i]:idx[i + 1]]) for i in range(n)]
        widths = [font.width(l, size) for l in cand]
        if max(widths) > maxw:
            continue
        score = max(widths) - 0.15 * min(widths)   # smal én niet te ongelijk
        if score < best_score - 1:
            best, best_score = cand, score
    return best


def split_cue(cue, nparts):
    """Knip een te lange cue in nparts stukken; liefst op een leesteken dicht bij
    de ideale grens, anders op woordgrens."""
    a, b, text = cue
    words = text.split()
    nw = len(words)
    grenzen = []
    start = 0
    for k in range(1, nparts):
        ideaal = round(nw * k / nparts)
        lo, hi = max(start + 1, ideaal - max(2, nw // (nparts * 3))), min(nw - 1, ideaal + max(2, nw // (nparts * 3)))
        best = None
        for j in range(lo, hi + 1):
            w = words[j - 1]
            if w[-1] in ",;:.!?—–" or w.endswith('"') or w.endswith("'"):
                score = abs(j - ideaal)
                if best is None or score < best[0]:
                    best = (score, j)
        j = best[1] if best else min(max(ideaal, start + 1), nw - 1)
        grenzen.append(j)
        start = j
    idx = [0] + grenzen + [nw]
    chunks = [" ".join(words[idx[i]:idx[i + 1]]) for i in range(len(idx) - 1) if idx[i + 1] > idx[i]]
    total = sum(len(c) for c in chunks) or 1
    out, t = [], a
    for c in chunks:
        d = (b - a) * len(c) / total
        out.append([t, t + d, c])
        t += d
    return out


# ═══════════════════════════════════════════════════════════════════
#  De bouwer
# ═══════════════════════════════════════════════════════════════════
class Clip:
    """Eén stuk opname op de tijdlijn.

    Een les mag uit meerdere opnames bestaan — je filmt zelden alles in één
    keer goed. Ze worden achter elkaar geplakt tot één doorlopende tijdlijn,
    en álle tijden in het storyboard (stappen, highlights, ondertitels) tellen
    op díé tijdlijn. Je hoeft dus nooit te rekenen met "clip 2 op 0:05": je
    kijkt gewoon naar de video zoals hij wordt.
    """

    def __init__(self, pad, van=None, tot=None, start=0.0):
        self.pad = pad
        self.bestandsduur = probe_duration(pad)
        self.van = max(0.0, ptime(van) or 0.0)
        self.tot = min(self.bestandsduur, ptime(tot) if tot is not None else self.bestandsduur)
        if self.tot <= self.van:
            die(f"clip {os.path.basename(pad)}: het stuk {ftime(self.van)}–{ftime(self.tot)} is leeg")
        self.duur = self.tot - self.van
        self.start = start                      # waar hij begint op de tijdlijn
        self.einde = start + self.duur
        self.src_w, self.src_h = probe_size(pad)
        self.audio = heeft_audio(pad)
        self.kader = None                       # wordt gezet zodra het formaat bekend is

    def lokaal(self, t):
        """Tijdlijn-seconde → seconde in dit bestand."""
        return self.van + max(0.0, min(self.duur, t - self.start))


class Kader:
    """Waar de bron in het uitvoerkader staat, en hoe coördinaten meeschuiven.

    Storyboard-coördinaten staan altijd in de **bronruimte**: de opname,
    passend geschaald in 1920×1080. Dat is precies wat `frame --raster` toont,
    en het blijft hetzelfde of je nu liggend rendert of als reel. Deze klasse
    rekent zo'n coördinaat om naar het uitvoerkader.

    Twee manieren om de bron in het kader te leggen:

    * **passen** — de hele opname past in beeld, met merkkleur erboven en
      eronder. Een breed scherm in een staand kader wordt dus een strook in
      het midden, met plaats voor een kop en ondertitels.
    * **vullen** — de opname vult het kader en wat er buiten valt wordt
      weggesneden. Dat is wat je wil bij een opname die al staand is, zoals
      een telefoonvideo van jezelf.

    Bij `auto` kiest hij zelf: vullen wanneer er nauwelijks iets wegvalt,
    anders passen. Zo hoef je er niets over te zeggen tot je het anders wil.
    """

    def __init__(self, src_w, src_h, uit_w, uit_h, modus="auto", midden=None,
                 veilig_boven=0, veilig_onder=0):
        self.src_w, self.src_h = max(1, src_w), max(1, src_h)
        self.uit_w, self.uit_h = uit_w, uit_h
        # bronruimte: de bron passend in 1920×1080 (de coördinaten van het storyboard)
        s = min(BRON_W / self.src_w, BRON_H / self.src_h)
        self.bron_w, self.bron_h = self.src_w * s, self.src_h * s
        if modus == "auto":
            modus = self._kies()
        self.modus = modus
        if modus == "vullen":
            self.schaal = max(uit_w / self.bron_w, uit_h / self.bron_h)
        else:
            self.schaal = min(uit_w / self.bron_w, uit_h / self.bron_h)
        bw, bh = self.bron_w * self.schaal, self.bron_h * self.schaal
        if midden and modus == "vullen":
            # `midden` is het punt uit de bronruimte dat in beeld moet blijven
            mx, my = float(midden[0]) * self.schaal, float(midden[1]) * self.schaal
            self.dx = min(max(uit_w / 2 - mx, uit_w - bw), 0.0)
            self.dy = min(max(uit_h / 2 - my, uit_h - bh), 0.0)
        else:
            # Bij een balk boven en onder centreren we tussen de veilige zones,
            # niet in het hele kader: de onderste strook gaat toch schuil onder
            # het bijschrift van de app, en zou het beeld anders omlaag trekken.
            self.dx = (uit_w - bw) / 2
            vrij_lo, vrij_hi = veilig_boven, uit_h - veilig_onder
            if bh < vrij_hi - vrij_lo:
                self.dy = vrij_lo + (vrij_hi - vrij_lo - bh) / 2
            else:
                self.dy = (uit_h - bh) / 2
        self.beeld = (self.dx, self.dy, bw, bh)

    def _kies(self):
        """Vullen zolang er weinig wegvalt; anders liever alles tonen."""
        vul = max(self.uit_w / self.bron_w, self.uit_h / self.bron_h)
        weg = 1 - (self.uit_w * self.uit_h) / (self.bron_w * vul * self.bron_h * vul)
        return "vullen" if weg <= 0.15 else "passen"

    # ── coördinaten ───────────────────────────────────────────────
    def punt(self, x, y):
        return x * self.schaal + self.dx, y * self.schaal + self.dy

    def gebied(self, g):
        """[x, y, breedte, hoogte] uit de bronruimte → uitvoerkader."""
        x, y = self.punt(float(g[0]), float(g[1]))
        return [x, y, float(g[2]) * self.schaal, float(g[3]) * self.schaal]

    def zichtbaar(self, g):
        """Valt dit gebied (deels) binnen het kader?"""
        x, y, w, h = self.gebied(g)
        return x + w > 0 and y + h > 0 and x < self.uit_w and y < self.uit_h

    # ── beeldpunten ───────────────────────────────────────────────
    def vf(self, vulkleur):
        """ffmpeg-filter die de bron op dezelfde plek legt als `punt` belooft.

        We schalen in één stap van de bron naar de eindmaat — niet eerst naar
        1920×1080 en dan verder — zodat een staande telefoonopname niet eerst
        verkleind en daarna weer opgeblazen wordt.
        """
        bw, bh = int(round(self.bron_w * self.schaal)), int(round(self.bron_h * self.schaal))
        bw += bw % 2
        bh += bh % 2
        c = "0x" + str(vulkleur).lstrip("#")
        delen = [f"scale={bw}:{bh}:flags=lanczos"]
        if self.modus == "vullen":
            x, y = int(round(-self.dx)), int(round(-self.dy))
            delen.append(f"crop={self.uit_w}:{self.uit_h}:{max(0, x)}:{max(0, y)}")
        else:
            x, y = int(round(self.dx)), int(round(self.dy))
            delen.append(f"pad={self.uit_w}:{self.uit_h}:{x}:{y}:color={c}")
        delen.append("setsar=1")
        return ",".join(delen)


class Bouwer:
    def __init__(self, lesdir, preview=False, venster=None, zonder_intro=False):
        self.lesdir = os.path.abspath(lesdir)
        self.preview = preview
        sb_path = os.path.join(self.lesdir, "storyboard.yaml")
        if not os.path.exists(sb_path):
            die(f"geen storyboard.yaml in {self.lesdir}")
        try:
            self.sb = yload(sb_path) or {}
        except YamlFout as e:
            die(f"storyboard.yaml: {e}")
        self.merk = laad_merk(self.sb.get("merk", STANDAARD_MERK))
        self.stijl = str(self.merk.get("stijl", "editorial"))
        self.clips = self._lees_clips()
        self.bron = self.clips[0].pad          # eerste clip, voor meldingen
        self.duur = self.clips[-1].einde       # de hele tijdlijn
        self.src_w, self.src_h = self.clips[0].src_w, self.clips[0].src_h

        # ── uitvoerformaat en waar de bron in het kader ligt ──
        fnaam = str(self.sb.get("formaat", "liggend"))
        if fnaam not in FORMATEN:
            die(f"onbekend formaat '{fnaam}' — kies uit: {', '.join(FORMATEN)}")
        self.formaat = fnaam
        fm = FORMATEN[fnaam]
        self.W, self.H = fm["breedte"], fm["hoogte"]
        self.marge = fm["marge"]
        # vormschaal: alles wat het hele kader vult (intro, outro) schaalt mee
        # met de breedte. tekstschaal: ondertitels en kaarten gaan hun eigen weg.
        self.s = self.W / 1920.0
        self.ts = float(fm["tekst_schaal"])
        # kaarten schalen minder hard mee dan ondertitels: een ondertitel moet
        # je van een afstand kunnen lezen, maar een kaart die een achtste van
        # het scherm inneemt duwt al het andere weg
        self.ks = float(fm["kaart_schaal"])
        self.rand = round(100 * self.s)
        self.titelbreedte = fm["titelbreedte"]
        self.ondertitelbreedte = fm["ondertitelbreedte"]
        self.veilig_boven = fm["veilig_boven"]
        self.veilig_onder = fm["veilig_onder"]
        self.veilig_rechts = fm["veilig_rechts"]
        # elke clip krijgt zijn eigen kader: een staande telefoonopname vult het
        # beeld en een breed scherm wordt een strook, ook als ze in dezelfde
        # video na elkaar komen
        for c in self.clips:
            c.kader = Kader(c.src_w, c.src_h, self.W, self.H,
                            str(self.sb.get("kader", "auto")), self.sb.get("kader_midden"),
                            self.veilig_boven, self.veilig_onder)
        self.kader = self.clips[0].kader
        # in een smal kader passen twee kaarten niet naast elkaar
        self.smal = self.W <= self.H   # reel én vierkant: Instagram-regels
        # tutorial (stappen, lesgevoel) of uitleg (gewoon vertellen)
        self.uitleg = str(self.sb.get("soort", "tutorial")).lower() == "uitleg"

        self.bezet_boven = []      # (A, B, onderkant) van wat er bovenaan staat
        self.uitdir = os.path.join(self.lesdir, "uit")
        os.makedirs(self.uitdir, exist_ok=True)
        self.waarschuwingen = []

        # fonts: elke rol is een keten ("ideaal | ook goed | overal aanwezig").
        # We zoeken op welk font er écht staat en gebruiken díe naam ook in de
        # ASS-tags, want libass vervangt een onbekende naam stilzwijgend door
        # iets anders — met andere breedtes dan wij hier opmeten.
        m = self.merk
        self.fontnaam, self.f = {}, {}
        ontbreekt = []
        for rol, sleutel in (("titel", "font_titel"), ("kop", "font_kop"),
                             ("label", "font_label"), ("tekst", "font_tekst"),
                             ("ondertitel", "font_ondertitel")):
            keten = m.get(sleutel) or m.get("font_kop") or STANDAARD_FONTS[rol]
            naam, font, gevonden = haal_font(keten)
            self.fontnaam[rol], self.f[rol] = naam, font
            if not gevonden:
                ontbreekt.append((sleutel, keten))
        if ontbreekt:
            for sleutel, keten in ontbreekt:
                self.waarschuwingen.append(
                    f"geen enkel font uit '{sleutel}: {keten}' staat op deze computer — "
                    f"breedtes worden geschat, vlakken kunnen scheef staan")
            self.waarschuwingen.append(
                "los dit op door een lettertype uit de keten te installeren, het "
                ".ttf-bestand in fonts/ te zetten, of in het merkbestand een font te "
                "kiezen dat je wél hebt (zie: ./reelstudio.sh dokter)")
        self.f_titel = self.f["titel"]
        self.f_kop = self.f["kop"]
        self.f_label = self.f["label"]
        self.f_tekst = self.f["tekst"]
        self.f_sub = self.f["ondertitel"]

        # tijdlijn
        knips = []
        for k in self.sb.get("knip") or []:
            if isinstance(k, dict):
                knips.append((ptime(k["van"]), ptime(k["tot"])))
            else:
                knips.append((ptime(k[0]), ptime(k[1])))
        versnels = []
        for v in self.sb.get("versnel") or []:
            versnels.append((ptime(v["van"]), ptime(v["tot"]), float(v.get("factor", 8))))
        self.knips, self.versnels = knips, versnels
        # Een storyboard mag zelf een fragment aanwijzen (van/tot). Dat is iets
        # anders dan --van/--tot op de opdrachtregel: dát is een snelle blik op
        # een stukje render, dus zonder intro en outro. Een fragment uit het
        # storyboard is de inhoud van de video zelf en hoort er wél bij.
        sb_van = ptime(self.sb.get("van")) if self.sb.get("van") is not None else None
        sb_tot = ptime(self.sb.get("tot")) if self.sb.get("tot") is not None else None
        lo = max(sb_van or 0.0, venster[0] if venster else 0.0)
        hi = min(self.duur if sb_tot is None else sb_tot, venster[1] if venster else self.duur)
        if hi <= lo:
            die(f"het fragment {ftime(lo)}–{ftime(hi)} is leeg — kijk van/tot na")
        self.venster = (lo, hi) if (sb_van is not None or sb_tot is not None or venster) else None
        self.tl = Tijdlijn(self.duur, knips, versnels, self.venster)

        self.intro_on = bool(self.sb.get("intro", True)) and not zonder_intro and (not venster or venster[0] <= lo)
        self.outro_on = bool(self.sb.get("outro", True)) and not zonder_intro and (not venster or venster[1] >= hi)
        # de duur van intro en outro hangt van het formaat af: een reel die vijf
        # seconden op een titelkaart blijft staan is al weggescrold
        self.intro_d = float(self.sb.get("intro_duur", m.get("intro_duur", fm["intro_duur"])
                                         if self.formaat == "liggend" else fm["intro_duur"])) if self.intro_on else 0.0
        self.outro_d = float(self.sb.get("outro_duur", m.get("outro_duur", fm["outro_duur"])
                                         if self.formaat == "liggend" else fm["outro_duur"])) if self.outro_on else 0.0
        self.body_start = self.intro_d
        self.body_end = self.intro_d + self.tl.totaal
        self.totaal = self.body_end + self.outro_d

        self.events = []   # (layer, start, end, text)
        self.zooms = []    # (t0, t1, factor, cx, cy) in brontijd

    # ── kleuren ───────────────────────────────────────────────────
    def kleur(self, naam):
        v = self.merk.get(naam, naam)
        if isinstance(v, str) and v.startswith("#"):
            return v
        v2 = self.merk.get(v)
        if isinstance(v2, str) and v2.startswith("#"):
            return v2
        return "#ff00ff"

    def c(self, naam, alpha=0.0):
        """Kleur als override-tags: \\1c&HBBGGRR&\\1a&HAA&  (alpha 0 = dekkend)."""
        hx = self.kleur(naam).lstrip("#")
        r, g, b = hx[0:2], hx[2:4], hx[4:6]
        return f"\\1c&H{b}{g}{r}&\\1a{a_tag(alpha)}"

    def c3(self, naam, alpha=0.0):
        """Randkleur (\\3c) als tags."""
        hx = self.kleur(naam).lstrip("#")
        r, g, b = hx[0:2], hx[2:4], hx[4:6]
        return f"\\3c&H{b}{g}{r}&\\3a{a_tag(alpha)}"

    @staticmethod
    def bandtekst(*delen):
        """Loopband-tekst uit losse stukken, met ✦ enkel tussen wat ingevuld is.

        Merkvelden mogen leeg zijn (niet elk merk heeft een website), en de
        titel mag een | bevatten als regeleinde — dat hoort niet in de band.
        """
        schoon = [str(d).replace("|", " ").strip() for d in delen if d and str(d).strip()]
        return "   ✦   ".join(schoon)

    def plaats_boven(self, A, B, hoogte, min_duur=1.4):
        """Plek zoeken voor iets dat in de band boven het beeld komt.

        Eerst proberen we het eronder te schuiven. Past het dan nog niet, dan
        wachten we tot wat er stond weg is — een kaart die twee seconden later
        verschijnt is oneindig veel beter dan een kaart die helemaal wegvalt.
        Geeft (y, starttijd) terug, of (None, None) als er echt geen plek is.
        """
        bx, by, bw, bh = self.kader.beeld
        grens = by - 12 if (self.smal and by > self.veilig_boven + 80) else self.H
        boven = self.marge + self.veilig_boven
        if self.smal and grens >= self.H:
            # Het beeld vult tot boven — op Instagram is dat bijna altijd een
            # camera-opname, en in het midden zit dan een gezicht. Kaarten
            # blijven in de bovenste strook; past het daar niet, dan schuiven
            # ze op in de tijd. Eén kaart mag altijd (anders valt ze weg).
            grens = max(self.veilig_boven + 0.16 * self.H, boven + hoogte + 8)
        momenten = [A] + sorted(b for (a, b, _o) in self.bezet_boven if A < b < B)
        for start in momenten:
            if B - start < min_duur:
                break
            y = boven
            for (a, b, onderkant) in self.bezet_boven:
                if start < b and B > a:
                    y = max(y, onderkant)
            if y + hoogte <= grens:
                return y, start
        return None, None

    def tem(self, v):
        """Lettergrootte voor tekst die gelézen moet worden.

        Meeschalen met de kaderbreedte alleen is niet genoeg: een reel wordt
        op een telefoon bekeken, dus tekst moet daar een grótere hap van het
        kader nemen dan in een liggende video op een scherm.
        """
        return v * self.s * self.ts

    def kaderkleur(self):
        """Kleur van de balken rond het beeld als de opname niet het hele
        kader vult. Standaard de donkere merkkleur: dat leest rustiger op een
        telefoon dan een lichte balk, en het beeld springt eruit."""
        return str(self.sb.get("kader_kleur") or self.merk.get("kader_kleur")
                   or ("ink" if self.formaat == "reel" else "creme"))

    def _lees_clips(self):
        """De opnames waaruit deze les bestaat, in volgorde.

        `clips:` is een lijst; `bron:` (één bestand) blijft werken en wordt
        gewoon een lijst van één. Zo blijven bestaande lessen ongewijzigd.
        """
        rijen = self.sb.get("clips")
        if not rijen:
            rijen = [{"bestand": self.sb.get("bron", "bron.mp4")}]
        elif isinstance(rijen, str):
            rijen = [{"bestand": rijen}]
        clips, t = [], 0.0
        for i, r in enumerate(rijen):
            if isinstance(r, str):
                r = {"bestand": r}
            naam = str(r.get("bestand") or r.get("bron") or "")
            if not naam:
                die(f"clip {i+1} heeft geen bestandsnaam")
            pad = naam if os.path.isabs(naam) else os.path.join(self.lesdir, naam)
            if not os.path.exists(pad):
                die(f"clip {i+1} niet gevonden: {pad}")
            c = Clip(pad, r.get("van"), r.get("tot"), t)
            clips.append(c)
            t = c.einde
        return clips

    def clip_op(self, t):
        """Welke clip staat er op deze tijdlijn-seconde?"""
        for c in self.clips:
            if t < c.einde - 1e-6:
                return c
        return self.clips[-1]

    def kader_op(self, t):
        """Het kader van de clip die op dit moment in beeld is.

        Coördinaten uit het storyboard horen bij de opname die op dat moment
        loopt, dus bij meerdere clips moet je het juiste kader nemen.
        """
        return self.clip_op(t).kader

    def kaartbreedte(self, deel=1.0):
        """Hoeveel ruimte een kaart mag innemen, binnen de veilige zone.

        In een liggend kader is dat ruim; in een reel moet de kaart tussen de
        marges én links van de knoppen van Instagram blijven.
        """
        beschikbaar = self.W - 2 * self.marge - self.veilig_rechts - 2 * 30 * self.ks
        return max(240.0, beschikbaar * deel)

    def font_tag(self, rol):
        """\\fn-tag met de fontnaam die op déze computer gevonden is."""
        return f"\\fn{self.fontnaam[rol]}"

    # ── lettergroottes: in échte pixels, font-onafhankelijk ───────
    @staticmethod
    def fs(font, em_px):
        """ASS-fontgrootte waarbij de em-grootte `em_px` pixels is."""
        e1 = font.em(1.0) if hasattr(font, "em") else 0.73
        return em_px / e1

    def sp(self, font, em_px, factor):
        """\\fsp-waarde (px) voor een spatiëring in em."""
        return f"\\fsp{em_px * factor:.1f}" if factor else ""

    def label_tekst(self, s):
        return str(s).upper() if self.merk.get("eyebrow_caps", False) else str(s)

    def eyebrow_tags(self, em_px, kleurnaam):
        f = self.f_label
        t = f"{self.font_tag('label')}\\fs{self.fs(f, em_px):.0f}\\bord0\\shad0{self.c(kleurnaam)}"
        if self.merk.get("eyebrow_caps", False):
            t += self.sp(f, em_px, float(self.merk.get("eyebrow_spatie", 0.06)))
        return t

    # ── mapping ───────────────────────────────────────────────────
    def T(self, t):
        """brontijd → uitvoertijd (incl. intro)."""
        return self.body_start + self.tl.out(t)

    def ev(self, start, end, text, layer=0):
        if end - start < 0.05:
            return
        self.events.append((layer, start, end, text))

    # ═══════════════════════════════════════════════════════════════
    #  Ondertitels
    # ═══════════════════════════════════════════════════════════════
    def bouw_ondertitels(self):
        srt = self.sb.get("ondertitels", "ondertitels.srt")
        path = os.path.join(self.lesdir, srt)
        if not os.path.exists(path):
            self.waarschuwingen.append(f"geen ondertitelbestand: {srt}")
            return
        cues = read_srt(path)
        m = self.merk
        font = self.f_sub
        em = float(m.get("ondertitel_em", 36)) * self.ts
        fsv = self.fs(font, em)
        lh = font.line_height(fsv)
        padx, pady = 28 * self.ts, 14 * self.ts
        onder = self.H - self.veilig_onder - float(m.get("ondertitel_onderrand", 40)) * self.ts
        maxregels = int(m.get("ondertitel_max_regels", 2))
        radius = min(float(m.get("radius_knop", 10)) * self.ts, 22 * self.ts)
        cam = self.sb.get("webcam")
        cx = self.W / 2
        maxw = self.ondertitelbreedte
        # Hoog schatten we de ondertitelband: genoeg om te weten of de webcam
        # er echt voor in de weg zit. In een liggend kader staat het bubbeltje
        # naast de ondertitels; in een reel staan die er meestal ver onder, en
        # dan hoeft de tekst niet smaller.
        band_hoog = maxregels * lh + 2 * pady
        if cam:
            cam_uit = self.kader.gebied(cam)
            raakt = (cam_uit[1] < onder and cam_uit[1] + cam_uit[3] > onder - band_hoog
                     and cam_uit[0] < self.W)
            if raakt:
                cx_l, cx_r = self.marge, cam_uit[0] - 24
                if cx_r > cx_l + 200:
                    maxw = min(maxw, 2 * min(self.W / 2 - cx_l, cx_r - self.W / 2))
                else:
                    self.waarschuwingen.append(
                        "de webcam-zone laat te weinig ruimte voor ondertitels — genegeerd")
        maxw_text = maxw - 2 * padx
        # Staat de ondertitel op de merkbalk naast het beeld in plaats van
        # erop? Dan is een pil in diezelfde kleur onzichtbaar. In dat geval
        # laten we hem weg en zetten we de tekst in de kleur die wél afsteekt —
        # precies de kale, grote ondertitel die je van een reel verwacht.
        bx, by, bw, bh = self.kader.beeld
        op_balk = (onder - band_hoog) > by + bh or onder < by
        pil_naam = m.get("ondertitel_pil", "ink")
        pil_uit = str(pil_naam).lower() in ("nee", "geen", "false")
        if op_balk and not pil_uit:
            pil_uit = self.kleur(pil_naam).lower() == self.kleur(self.kaderkleur()).lower()
        pil_col = self.c(pil_naam, 1 - float(m.get("ondertitel_pil_alpha", 0.92)))
        if pil_uit:
            balk_donker = is_donker(self.kleur(self.kaderkleur()))
            txt_col = self.c("creme" if balk_donker else "ink")
        else:
            txt_col = self.c(m.get("ondertitel_tekst", "creme"))
        fn = self.font_tag("ondertitel")

        final = []
        for cue in cues:
            lines = wrap(cue[2], font, fsv, maxw_text)
            if len(lines) <= maxregels:
                final.append(cue)
            else:
                final.extend(split_cue(cue, math.ceil(len(lines) / maxregels)))
        n = 0
        gemeld = 0
        for a, b, text in final:
            A, B = self.T(a), self.T(b)
            if B - A < 0.15:
                continue
            for va, vb, _f in self.versnels:
                if a < vb - 0.3 and b > va + 0.3 and gemeld < 8:
                    self.waarschuwingen.append(f"ondertitel op {ftime(a)} valt (deels) in een versneld stuk {ftime(va)}–{ftime(vb)}: '{text[:40]}…' — versnel-venster verkleinen of cue hertimen")
                    gemeld += 1
                    break
            lines = wrap(text, font, fsv, maxw_text)
            wmax = max(font.width(l, fsv) for l in lines)
            pw = wmax + 2 * padx
            ph = len(lines) * lh + 2 * pady
            px = cx - pw / 2
            py = onder - ph
            body = "\\N".join(esc(l) for l in lines)
            fade = "\\fad(120,120)"
            if not pil_uit:
                self.ev(A, B, f"{{\\an7\\pos({px:.1f},{py:.1f}){fade}\\bord0\\shad0{pil_col}\\p1}}{rrect(0,0,pw,ph,radius)}{{\\p0}}", layer=10)
            self.ev(A, B, f"{{\\an2\\pos({cx:.1f},{onder - pady:.1f}){fade}{fn}\\fs{fsv:.0f}\\bord0\\shad0{txt_col}}}{body}", layer=11)
            n += 1
        self.n_subs = n

    # ═══════════════════════════════════════════════════════════════
    #  Kaarten (stap, tip, prompt)
    # ═══════════════════════════════════════════════════════════════
    def kaart(self, start, end, x, y, w, h, vanaf="links", layer=20):
        """Kaart in merkstijl die in schuift: wit/crème, radius_kaart, optioneel
        schaduw of dun randje. Geeft de \\move- en \\fad-tags terug."""
        m = self.merk
        r = float(m.get("radius_kaart", 18))
        bg = self.c(m.get("kaart_achtergrond", "wit"), 1 - float(m.get("kaart_alpha", 0.97)))
        dx = -40 if vanaf == "links" else (40 if vanaf == "rechts" else 0)
        dy = -30 if vanaf == "boven" else 0
        mv = f"\\move({x+dx:.1f},{y+dy:.1f},{x:.1f},{y:.1f},0,380)"
        fade = "\\fad(260,260)"
        if m.get("kaart_schaduw", False):
            self.ev(start, end, f"{{\\an7{mv}{fade}\\bord0\\shad0\\blur18{self.c('ink', 0.86)}\\p1}}{rrect(4,10,w,h,r)}{{\\p0}}", layer=layer)
        rand = m.get("kaart_rand", False)
        if rand and rand is not True:
            self.ev(start, end, f"{{\\an7{mv}{fade}\\bord0\\shad0{self.c(rand)}\\p1}}{rrect(-1.5,-1.5,w+3,h+3,r+1.5)}{{\\p0}}", layer=layer)
        self.ev(start, end, f"{{\\an7{mv}{fade}\\bord0\\shad0{bg}\\p1}}{rrect(0,0,w,h,r)}{{\\p0}}", layer=layer + 1)
        return mv, fade

    def chip(self, start, end, x, y, tekst, layer=20, rechts_uitlijnen=False, accent_prefix=None):
        """Klein pilletje (stap-chip, versnel-chip)."""
        m = self.merk
        em = 21 * self.ks
        fsv = self.fs(self.f_label, em)
        # in een smal kader staat rechtsboven vaak een tip- of promptkaart;
        # een chip die daaronder doorloopt is onleesbaar, dus korten we in
        maxw = self.kaartbreedte(0.5) - (self.f_label.width(accent_prefix + "  ", fsv)
                                         if accent_prefix else 0)
        tekst = kort_af(str(tekst), self.f_label, fsv, maxw)
        tw = self.f_label.width(tekst, fsv) + (self.f_label.width(accent_prefix + "  ", fsv) if accent_prefix else 0)
        cw, ch = tw + 2 * 20 * self.ks, self.f_label.line_height(fsv) + 2 * 10 * self.ks
        if rechts_uitlijnen:
            x = x - cw
        self.ev(start, end, f"{{\\an7\\pos({x:.1f},{y:.1f})\\fad(300,300)\\bord0\\shad0{self.c(m.get('chip_achtergrond','ink'), 0.06)}\\p1}}{rrect(0,0,cw,ch,ch/2)}{{\\p0}}", layer=layer)
        txt = esc(tekst)
        if accent_prefix:
            txt = f"{{{self.c('accent')}}}{esc(accent_prefix)}  {{{self.c(m.get('chip_tekst','creme'))}}}{txt}"
        self.ev(start, end, f"{{\\an7\\pos({x+20:.1f},{y+10:.1f})\\fad(300,300){self.font_tag('label')}\\fs{fsv:.0f}\\bord0\\shad0{self.c(m.get('chip_tekst','creme'))}}}{txt}", layer=layer + 2)
        return cw, ch

    def bouw_stappen(self):
        stappen = self.sb.get("stappen") or []
        if not stappen:
            return
        m = self.merk
        n = len(stappen)
        toon_chip = bool(self.sb.get("stapchip", True))
        kaart_duur = float(self.sb.get("stapkaart_duur", 5.0))
        em_t, em_e = 34 * self.ks, 15 * self.ks
        fs_t = self.fs(self.f_kop, em_t)
        fs_e = self.fs(self.f_label, em_e)
        ink = self.c(m.get("kaart_tekst", "ink"))
        eye_k = m.get("kaart_eyebrow", "accent")
        genummerd = [s for s in stappen if s.get("nummer", "auto") != 0]
        n_echt = len(genummerd)
        for i, s in enumerate(stappen):
            t0 = ptime(s.get("van", 0))
            t1 = ptime(stappen[i + 1]["van"]) if i + 1 < n else self.duur
            A, B = self.T(t0), self.T(t1)
            if B - A < 0.2:
                continue
            titel = str(s.get("titel", f"Stap {i+1}"))
            nummer = s.get("nummer", "auto")
            if nummer == "auto":
                nummer = genummerd.index(s) + 1
            label = s.get("label") or (f"Stap {nummer} van {n_echt}" if nummer else "")
            label = self.label_tekst(label)
            kd = float(s.get("duur", kaart_duur))
            card_end = min(A + kd, B)
            lines = wrap_balanced(titel, self.f_kop, fs_t, self.kaartbreedte())
            tw = max(self.f_kop.width(l, fs_t) for l in lines)
            ew = self.f_label.width(label, fs_e) * 1.08 if label else 0
            padx, pady = 30 * self.ks, 24 * self.ks
            w = max(tw, ew) + 2 * padx
            lh = self.f_kop.line_height(fs_t)
            eh = self.f_label.line_height(fs_e) + 8 if label else 0
            h = pady + eh + len(lines) * lh + pady
            x = self.marge
            y, A_k = self.plaats_boven(A, card_end, h)
            if y is None:
                self.waarschuwingen.append(
                    f"stapkaart op {ftime(t0)} past nergens boven het beeld — "
                    f"kort de titel in of maak de hook korter")
                y, A_k = self.marge + self.veilig_boven, A
            elif A_k > A + 0.05:
                self.waarschuwingen.append(
                    f"stapkaart op {ftime(t0)} start {A_k - A:.1f}s later; eerder was het beeld bezet")
            self.bezet_boven.append((A_k, card_end, y + h + 16 * self.s))
            mv, fade = self.kaart(A_k, card_end, x, y, w, h, vanaf="links")
            A = A_k
            ty = y + pady
            mvx = lambda xx, yy: f"\\move({xx-40:.1f},{yy:.1f},{xx:.1f},{yy:.1f},0,380)"
            if label:
                self.ev(A, card_end, f"{{\\an7{mvx(x+padx, ty)}{fade}{self.eyebrow_tags(em_e, eye_k)}}}{esc(label)}", layer=22)
                ty += eh
            body = "\\N".join(esc(l) for l in lines)
            self.ev(A, card_end, f"{{\\an7{mvx(x+padx, ty)}{fade}{self.font_tag('kop')}\\fs{fs_t:.0f}{self.sp(self.f_kop, em_t, float(m.get('kop_spatie', 0)))}\\bord0\\shad0{ink}}}{body}", layer=22)
            if toon_chip and B - card_end > 1.0:
                cy, _ = self.plaats_boven(card_end, B, 46 * self.ks)
                cy = self.marge + self.veilig_boven if cy is None else cy
                self.chip(card_end, B, x, cy, titel, accent_prefix=(str(nummer) if nummer else None))

    def bouw_kaarten_rechts(self):
        """Tips en prompt-kaarten rechtsboven. Bewaakt dat ze elkaar niet overlappen."""
        m = self.merk
        items = [("tip", t) for t in (self.sb.get("tips") or [])] + [("prompt", p) for p in (self.sb.get("prompts") or [])]
        if not items:
            return
        ink = self.c(m.get("kaart_tekst", "ink"))
        sub_col = self.c(m.get("kaart_subtekst", "grijs"))
        eye_k = m.get("kaart_eyebrow", "accent")
        em_e, em_b, em_s = 15 * self.ks, 25 * self.ks, 18 * self.ks
        fs_e = self.fs(self.f_label, em_e)
        fs_b = self.fs(self.f_tekst, em_b)
        fs_bk = self.fs(self.f_kop, em_b + 3)
        fs_s = self.fs(self.f_tekst, em_s)
        bezet = []
        for soort, it in sorted(items, key=lambda z: ptime(z[1].get("van", 0))):
            t0 = ptime(it.get("van", 0))
            dur = float(it.get("duur", 6 if soort == "tip" else 7))
            A = self.T(t0)
            B = min(self.T(t0 + dur), self.body_end) if "tot" not in it else self.T(ptime(it["tot"]))
            if B - A < 0.3:
                continue
            for (a0, b0) in bezet:
                if A < b0 and B > a0:
                    self.waarschuwingen.append(f"{soort}-kaart op {ftime(t0)} overlapt met een andere kaart rechtsboven (verschoven)")
                    A = max(A, b0 + 0.2)
                    B = max(B, A + 3.0)
            bezet.append((A, B))
            if soort == "tip":
                label = self.label_tekst(it.get("label", "Tip"))
                bodyfont, bfs = self.f_tekst, fs_b
                lines = wrap(str(it.get("tekst", "")), bodyfont, bfs, self.kaartbreedte(0.68))
                sub = None
            else:
                label = self.label_tekst(f"Prompt {it.get('nummer', '')}".strip())
                bodyfont, bfs = self.f_kop, fs_bk
                lines = wrap(str(it.get("titel", "")), bodyfont, bfs, self.kaartbreedte(0.68))
                sub = str(it.get("tekst", "De volledige tekst staat onder deze les"))
            lh = bodyfont.line_height(bfs)
            tw = max([bodyfont.width(l, bfs) for l in lines] + [self.f_label.width(label, fs_e) * 1.08] +
                     ([self.f_tekst.width(sub, fs_s)] if sub else []))
            padx, pady = 30 * self.ks, 24 * self.ks
            w = tw + 2 * padx
            eh = self.f_label.line_height(fs_e) + 8
            h = pady + eh + len(lines) * lh + (self.f_tekst.line_height(fs_s) + 8 if sub else 0) + pady
            if self.smal:
                # links uitlijnen en onder wat er al staat schuiven: naast elkaar
                # passen ze niet in een staand kader
                x = self.marge
                y, A2 = self.plaats_boven(A, B, h)
                if y is None:
                    self.waarschuwingen.append(
                        f"{soort}-kaart op {ftime(t0)} past nergens naast wat er al staat — "
                        f"zet hem een paar seconden later")
                    continue
                if A2 > A + 0.05:
                    self.waarschuwingen.append(
                        f"{soort}-kaart op {ftime(t0)} start {A2 - A:.1f}s later; eerder was het beeld bezet")
                A = A2
                self.bezet_boven.append((A, B, y + h + 16 * self.s))
                mv, fade = self.kaart(A, B, x, y, w, h, vanaf="links")
            else:
                x, y = self.W - self.marge - self.veilig_rechts - w, self.marge + self.veilig_boven
                mv, fade = self.kaart(A, B, x, y, w, h, vanaf="rechts")
            ty = y + pady
            mv_t = lambda yy: f"\\move({x+padx+40:.1f},{yy:.1f},{x+padx:.1f},{yy:.1f},0,380)"
            self.ev(A, B, f"{{\\an7{mv_t(ty)}{fade}{self.eyebrow_tags(em_e, eye_k)}}}{esc(label)}", layer=22)
            ty += eh
            body = "\\N".join(esc(l) for l in lines)
            fnb = self.font_tag("kop" if soort == "prompt" else "tekst")
            spb = self.sp(self.f_kop, em_b + 3, float(m.get("kop_spatie", 0))) if soort == "prompt" else ""
            self.ev(A, B, f"{{\\an7{mv_t(ty)}{fade}{fnb}\\fs{bfs:.0f}{spb}\\bord0\\shad0{ink}}}{body}", layer=22)
            ty += len(lines) * lh + 8
            if sub:
                self.ev(A, B, f"{{\\an7{mv_t(ty)}{fade}{self.font_tag('tekst')}\\fs{fs_s:.0f}\\bord0\\shad0{sub_col}}}{esc(sub)}", layer=22)

    # ═══════════════════════════════════════════════════════════════
    #  Highlights (spotlight + rand + label, optioneel zoom)
    # ═══════════════════════════════════════════════════════════════
    def zoom_venster(self, z, cx, cy):
        ww, wh = self.W / z, self.H / z
        wx = min(max(cx - ww / 2, 0), self.W - ww)
        wy = min(max(cy - wh / 2, 0), self.H - wh)
        return wx, wy, z

    def bouw_highlights(self):
        m = self.merk
        hl = m.get("highlight_kleur", "accent")
        hl_col = self.c(hl)
        dim_col_name = m.get("dim_kleur", "ink")
        dim_default = float(m.get("dim_sterkte", 0.34))
        cam = self.sb.get("webcam")
        em_l = 23 * self.ts
        fs_l = self.fs(self.f_sub, em_l)
        radius = float(m.get("radius_knop", 10)) * self.ts
        last_zoom_end = -1
        for h in self.sb.get("highlights") or []:
            t0, t1 = ptime(h.get("van")), ptime(h.get("tot"))
            if t0 is None or t1 is None:
                self.waarschuwingen.append("highlight zonder van/tot overgeslagen")
                continue
            if "gebied" not in h:
                self.waarschuwingen.append(f"highlight op {ftime(t0)} zonder gebied overgeslagen")
                continue
            # het storyboard geeft het gebied in broncoördinaten; in een reel
            # ligt de opname elders in beeld en soms valt het gebied er buiten
            kdr = self.kader_op(t0)
            if not kdr.zichtbaar(h["gebied"]):
                self.waarschuwingen.append(
                    f"highlight op {ftime(t0)} valt buiten het {self.formaat}-kader — overgeslagen")
                continue
            gx, gy, gw, gh = kdr.gebied(h["gebied"])
            z = float(h.get("zoom", 1) or 1)
            dim = h.get("dim", True)
            dim_s = dim_default if dim is True else (0.0 if dim is False else float(dim))
            A, B = self.T(t0), self.T(t1)
            if B - A < 0.3:
                continue
            if z > 1.001:
                if t0 < last_zoom_end + 0.2:
                    self.waarschuwingen.append(f"zoom op {ftime(t0)} overlapt met vorige zoom — overgeslagen")
                    z = 1.0
                else:
                    self.zooms.append((t0, t1, z, gx + gw / 2, gy + gh / 2))
                    last_zoom_end = t1
            if z > 1.001:
                wx, wy, _ = self.zoom_venster(z, gx + gw / 2, gy + gh / 2)
                bx, by, bw, bh = (gx - wx) * z, (gy - wy) * z, gw * z, gh * z
                A2, B2 = A + RAMP, B - RAMP
            else:
                bx, by, bw, bh = gx, gy, gw, gh
                A2, B2 = A, B
            if B2 - A2 < 0.3:
                continue
            pad = 10
            rx, ry, rw, rh = bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad
            dur_ms = int((B2 - A2) * 1000)
            if dim_s > 0:
                self.ev(A2, B2, f"{{\\an7\\pos(0,0)\\fad(300,300)\\bord0\\shad0{self.c(dim_col_name, 1 - dim_s)}\\iclip({rx:.0f},{ry:.0f},{rx+rw:.0f},{ry+rh:.0f})\\p1}}m 0 0 l {self.W} 0 l {self.W} {self.H} l 0 {self.H}{{\\p0}}", layer=30)
            puls = ""
            t = 400
            while t + 1400 < dur_ms:
                puls += f"\\t({t},{t+700},\\1a{a_tag(0.45)})\\t({t+700},{t+1400},\\1a{a_tag(0.0)})"
                t += 1400
            pop = "\\fscx112\\fscy112\\t(0,280,\\fscx100\\fscy100)"
            self.ev(A2, B2, f"{{\\an7\\pos({rx+rw/2:.1f},{ry+rh/2:.1f})\\fad(250,250){pop}{puls}\\bord0\\shad0{hl_col}\\p1}}{ring(-rw/2, -rh/2, rw, rh, min(radius + 4, 16), 5)}{{\\p0}}", layer=31)
            tekst = h.get("tekst")
            if tekst:
                lw = self.f_sub.width(str(tekst), fs_l) + 2 * 20
                lhh = self.f_sub.line_height(fs_l) + 2 * 10
                lx = min(max(rx + rw / 2 - lw / 2, 24), self.W - 24 - lw)
                onder = ry + rh + 16 + lhh
                plaats = h.get("label", "auto")
                below_ok = onder < self.H - self.veilig_onder - 150
                if cam and below_ok:
                    cx0, cy0, cw0, ch0 = kdr.gebied(cam)
                    if z <= 1.001 and lx < cx0 + cw0 and lx + lw > cx0 and ry + rh + 16 < cy0 + ch0 and onder > cy0:
                        below_ok = False
                if plaats == "boven" or (plaats == "auto" and not below_ok):
                    ly = ry - 16 - lhh
                    tri = triangle(rx + rw / 2, ly + lhh + 9, 9, "onder")
                else:
                    ly = ry + rh + 16
                    tri = triangle(rx + rw / 2, ly - 9, 9, "boven")
                self.ev(A2 + 0.15, B2, f"{{\\an7\\pos(0,0)\\fad(200,200)\\bord0\\shad0{hl_col}\\p1}}{rrect(lx, ly, lw, lhh, min(radius, lhh/2))} {tri}{{\\p0}}", layer=32)
                self.ev(A2 + 0.15, B2, f"{{\\an7\\pos({lx+20:.1f},{ly+10:.1f})\\fad(200,200){self.font_tag('ondertitel')}\\fs{fs_l:.0f}\\bord0\\shad0{self.c('wit')}}}{esc(tekst)}", layer=33)

    # ═══════════════════════════════════════════════════════════════
    #  Versnel-chip
    # ═══════════════════════════════════════════════════════════════
    def bouw_versnelchips(self):
        for a, b, f in self.tl.versnelde_stukken():
            A, B = self.body_start + a, self.body_start + b
            if B - A < 0.4:
                continue
            txt = str(self.sb.get("versnel_tekst", "Claude werkt — versneld")) + f" ×{f:g}"
            # gecentreerd bovenaan: eerst breedte schatten
            fsv = self.fs(self.f_label, 21)
            cw = self.f_label.width("»  " + txt, fsv) + 40
            self.chip(A, B, self.W / 2 - cw / 2, self.marge + self.veilig_boven, txt,
                      layer=40, accent_prefix="»")

    # ═══════════════════════════════════════════════════════════════
    #  Intro / outro — stijl "editorial"
    # ═══════════════════════════════════════════════════════════════
    def wordmark(self, start, end, x, y, em, op_donker=False, layer=5, fade="\\fad(400,300)"):
        """Het wordmark in drie kleuren: gewoon, accent, gedempt.

        Welk stuk het accent krijgt zegt het merkbestand zelf:

            wordmark: ASKLIEN.ai
            wordmark_accent: LIEN      # dit stuk in de accentkleur
            wordmark_gedempt: .ai      # dit stuk gedempt

        Zonder die sleutels valt de laatste punt-extensie (".ai", ".be") vanzelf
        gedempt uit en blijft de rest in de hoofdkleur — goed genoeg voor de
        meeste merknamen, en niets is hardgecodeerd op één merk.
        """
        m = self.merk
        wm = str(m.get("wordmark", m.get("site", m.get("naam", "MERK"))))
        hoofd = "creme" if op_donker else "ink"
        gedempt_kl = "muted_donker" if op_donker else "muted"
        accent_txt = str(m.get("wordmark_accent", "") or "")
        gedempt_txt = str(m.get("wordmark_gedempt", "") or "")
        if not accent_txt and not gedempt_txt:
            punt = wm.rfind(".")
            if punt > 0:
                gedempt_txt = wm[punt:]
        delen = [(wm, hoofd)]
        for stuk, kleur in ((accent_txt, "accent"), (gedempt_txt, gedempt_kl)):
            if not stuk:
                continue
            nieuw_delen = []
            for tekst, kl in delen:
                i = tekst.lower().find(stuk.lower()) if kl == hoofd else -1
                if i < 0:
                    nieuw_delen.append((tekst, kl))
                else:
                    nieuw_delen += [(tekst[:i], kl), (tekst[i:i + len(stuk)], kleur),
                                    (tekst[i + len(stuk):], kl)]
            delen = nieuw_delen
        delen = [(t, k) for t, k in delen if t]
        f = self.f_titel
        fsv = self.fs(f, em)
        sp = self.sp(f, em, float(m.get("kop_spatie", 0)))
        xx = x
        for tekst, kl in delen:
            if not tekst:
                continue
            self.ev(start, end, f"{{\\an7\\pos({xx:.1f},{y:.1f}){fade}{self.font_tag('titel')}\\fs{fsv:.0f}{sp}\\bord0\\shad0{self.c(kl)}}}{esc(tekst)}", layer=layer)
            xx += f.width(tekst, fsv) + em * float(m.get("kop_spatie", 0)) * len(tekst)
        return xx - x

    def band(self, start, end, y, h, bg, fg, tekst, snelheid=140, layer=4):
        """Marquee-band: tekst schuift langzaam naar links (zoals de site)."""
        m = self.merk
        em = 22
        f = self.f_kop
        fsv = self.fs(f, em)
        sp = self.sp(f, em, 0.08)
        self.ev(start, end, f"{{\\an7\\pos(0,{y:.0f})\\bord0\\shad0{self.c(bg)}\\p1}}m 0 0 l {self.W} 0 l {self.W} {h:.0f} l 0 {h:.0f}{{\\p0}}", layer=layer)
        unit = f"{tekst}   ✦   "
        uw = f.width(unit, fsv) + em * 0.08 * len(unit)
        reps = int(self.W / uw) + 3
        full = (unit * reps).upper()
        dur_ms = int((end - start) * 1000)
        verschuiving = snelheid * (end - start)
        x0 = 0
        self.ev(start, end, f"{{\\an4\\move({x0:.0f},{y + h/2:.0f},{x0 - verschuiving:.0f},{y + h/2:.0f},0,{dur_ms}){self.font_tag('kop')}\\fs{fsv:.0f}{sp}\\bord0\\shad0{self.c(fg)}}}{esc(full)}", layer=layer + 1)

    def titelhoogte(self, titel, em, maxw):
        """Hoe hoog een kop wordt, zonder hem al te tekenen."""
        f = self.f_titel
        fsv = self.fs(f, em)
        return len(wrap_balanced(titel, f, fsv, maxw)) * f.line_height(fsv) * 0.98

    def _titel_met_accent(self, start, end, x, y, titel, em, maxw, kleur_basis, accent_laatste=True, onderlijn=True, fade="\\fad(450,400)", rise_d=120, layer=5):
        """Grote kop: laatste regel in accentkleur + dikke onderlijn onder het
        laatste woord (hero-signatuur van de site). Geeft de hoogte terug."""
        m = self.merk
        f = self.f_titel
        fsv = self.fs(f, em)
        spf = float(m.get("kop_spatie", 0))
        sp = self.sp(f, em, spf)
        lines = wrap_balanced(titel, f, fsv, maxw)
        lh = f.line_height(fsv) * 0.98
        rise = lambda xx, yy, d=0: f"\\move({xx:.1f},{yy+26:.1f},{xx:.1f},{yy:.1f},{d},{d+650})"
        yy = y
        for i, line in enumerate(lines):
            laatste = (i == len(lines) - 1)
            kl = "accent" if (laatste and accent_laatste and len(lines) > 1) else kleur_basis
            self.ev(start, end, f"{{\\an7{rise(x, yy, rise_d)}{fade}{self.font_tag('titel')}\\fs{fsv:.0f}{sp}\\bord0\\shad0{self.c(kl)}}}{esc(line)}", layer=layer)
            if laatste and onderlijn:
                woorden = line.split()
                laatste_woord = woorden[-1].rstrip(".,!?")
                w_line = f.width(line, fsv) + em * spf * len(line)
                w_last = f.width(laatste_woord, fsv) + em * spf * len(laatste_woord)
                w_punt = f.width(woorden[-1][len(laatste_woord):], fsv)
                ux = x + w_line - w_last - w_punt
                uy = yy + f.ascent(fsv) + em * 0.10
                dikte = max(6, em * 0.11)
                kl_l = "creme" if kleur_basis == "creme" else "ink"
                self.ev(start, end, f"{{\\an7{rise(ux, uy, rise_d + 250)}{fade}\\bord0\\shad0{self.c(kl_l)}\\p1}}m 0 0 l {w_last:.0f} 0 l {w_last:.0f} {dikte:.0f} l 0 {dikte:.0f}{{\\p0}}", layer=layer)
            yy += lh
        return yy - y

    def pills(self, start, end, x, y, items, em=24, stijl="outline", op_donker=False, maxw=1500, layer=5, fade="\\fad(450,400)", d0=300):
        """Rij pilletjes. stijl: outline (2px rand) | vol (inkt/crème gevuld)."""
        m = self.merk
        f = self.f_label
        fsv = self.fs(f, em)
        px, py = x, y
        ph = f.line_height(fsv) + 2 * 12
        rise = lambda xx, yy, d=0: f"\\move({xx:.1f},{yy+26:.1f},{xx:.1f},{yy:.1f},{d},{d+650})"
        for i, p in enumerate(items or []):
            txt = str(p)
            pw = f.width(txt, fsv) + 2 * 24
            if px + pw > x + maxw:
                px = x
                py += ph + 14
            d = d0 + i * 110
            rk = ph / 2
            if stijl == "outline":
                rand = "creme" if op_donker else "ink"
                self.ev(start, end, f"{{\\an7{rise(px, py, d)}{fade}\\bord0\\shad0{self.c(rand)}\\p1}}{ring(0,0,pw,ph,rk,2)}{{\\p0}}", layer=layer)
                tk = rand
            else:
                bgk = "creme" if op_donker else "ink"
                self.ev(start, end, f"{{\\an7{rise(px, py, d)}{fade}\\bord0\\shad0{self.c(bgk)}\\p1}}{rrect(0,0,pw,ph,rk)}{{\\p0}}", layer=layer)
                tk = "ink" if op_donker else "creme"
            self.ev(start, end, f"{{\\an7{rise(px+24, py+12, d)}{fade}{self.font_tag('label')}\\fs{fsv:.0f}\\bord0\\shad0{self.c(tk)}}}{esc(txt)}", layer=layer + 1)
            px += pw + 14
        return py + ph - y

    def bouw_intro(self):
        if not self.intro_on:
            return
        if self.stijl != "editorial":
            return self._intro_gradient()
        sb, m = self.sb, self.merk
        A, B = 0.0, self.intro_d - 0.35
        fade = "\\fad(400,350)"
        # wordmark + les-label
        self.wordmark(A, B, self.rand, (84 + self.veilig_boven) * self.s, self.tem(40))
        reeks = None if self.uitleg else sb.get("reeks")
        if reeks:
            txt = self.label_tekst(reeks)
            em = self.tem(17)
            fsv = self.fs(self.f_label, em)
            pw = self.f_label.width(txt, fsv) * 1.08 + 2 * 20
            ph = self.f_label.line_height(fsv) + 2 * 10
            self.ev(A, B, f"{{\\an7\\pos({self.W-self.rand-pw:.1f},{(84 + self.veilig_boven) * self.s - 2:.1f}){fade}\\bord0\\shad0{self.c('ink')}\\p1}}{rrect(0,0,pw,ph,float(m.get('radius_knop',10)))}{{\\p0}}", layer=5)
            self.ev(A, B, f"{{\\an7\\pos({self.W-self.rand-pw+20:.1f},{(84 + self.veilig_boven) * self.s - 2 + 10:.1f}){fade}{self.eyebrow_tags(em, 'creme')}}}{esc(txt)}", layer=6)
        # titel + pills, verticaal gecentreerd tussen kop en band
        titel = str(sb.get("titel", ""))
        em_t = self.tem(104)
        f = self.f_titel
        fsv = self.fs(f, em_t)
        lines = wrap_balanced(titel, f, fsv, self.titelbreedte)
        th = len(lines) * f.line_height(fsv) * 0.98
        punten = [] if self.uitleg else (sb.get("intro_punten") or [])
        ph = (self.f_label.line_height(self.fs(self.f_label, self.tem(24))) + (24 + 40) * self.s) if punten else 0
        band_y = self.H - self.veilig_onder - 110
        top, bottom = (200 + self.veilig_boven) * self.s, band_y - 40
        y = top + max(0, (bottom - top - th - ph) / 2)
        h_t = self._titel_met_accent(A, B, self.rand, y, titel, em_t, self.titelbreedte, "ink")
        if punten:
            self.pills(A, B, self.rand, y + h_t + 44 * self.s, punten, em=self.tem(24), stijl="outline")
        # marquee-band onderaan
        band_txt = self.bandtekst(m.get("band_tekst", m.get("naam", "")), m.get("site", ""),
                                  f"{reeks} · {titel}" if reeks else "")
        self.band(A, self.intro_d, band_y, 110 * self.s, m.get("band_achtergrond", "ink"), m.get("band_tekstkleur", "creme"), band_txt)

    def look_vf(self):
        """Extra filters op het bronbeeld, vóór de overlays.

        `look: warm` doet wat je anders in CapCut doet voor je het hier
        invoert: iets warmer (bruiner), een zachtere huid en net wat meer
        kleur in gedempte tinten zoals lippen. Het is een grade over het
        hele beeld — geen gezichtsherkenning — maar op een headshot is dat
        precies waar het zit. Bewust subtiel: dit moet je in een vergelijking
        zien, niet in het beeld zelf.
        """
        look = str(self.sb.get("look", "naturel")).lower()
        if look in ("naturel", "geen", "nee", ""):
            return ""
        if look == "warm":
            return (",hqdn3d=1.5:1.5:3:3"
                    ",colortemperature=temperature=5800:pl=0.85"
                    ",vibrance=intensity=0.18"
                    ",eq=saturation=1.04:gamma=1.02")
        self.waarschuwingen.append(f"onbekende look '{look}' — naturel gebruikt")
        return ""

    def outro_velden(self):
        """(eyebrow, titel, punten, volgende) — met andere standaardwaarden
        voor uitleg dan voor een tutorial.

        Een uitleg-reel is geen les: "Dat heb je nu" met "Resultaat 1,
        Resultaat 2" slaat daar nergens op. De eindkaart is daar één ding:
        volg voor meer, met de knop.
        """
        sb, m = self.sb, self.merk
        if self.uitleg:
            # Oudere storyboards dragen het les-vulsel van het sjabloon nog mee
            # ("Dat heb je nu", "Goed gedaan.", Resultaat 1/2). Wie zijn video
            # op uitleg zet bedoelt: weg met dat lesgevoel — dus alleen wat er
            # bewust anders ingezet is, telt.
            def eigen(sleutel, vulsel):
                v = sb.get(sleutel)
                return None if v is None or v == vulsel else v
            eyebrow = eigen("outro_eyebrow", "Dat heb je nu")
            titel = eigen("outro_titel", "Goed gedaan.")
            punten = eigen("outro_punten", ["Resultaat 1", "Resultaat 2"]) or []
            volgende = eigen("outro_volgende", "Volgende les: …")
            titel = str(titel if titel is not None else (volgende or "Volg voor meer"))
            if volgende and str(volgende).strip().lower() == titel.strip().lower():
                # anders staat dezelfde tekst groot én op de knop
                volgende = m.get("site") or None
            return (str(eyebrow if eyebrow is not None else m.get("site", "") or ""),
                    titel, punten, volgende)
        return (str(sb.get("outro_eyebrow", "Dat heb je nu")),
                str(sb.get("outro_titel", "Goed gedaan.")),
                sb.get("outro_punten") or [], sb.get("outro_volgende"))

    def bouw_outro(self):
        if not self.outro_on:
            return
        if self.stijl != "editorial":
            return self._outro_gradient()
        if self.uitleg:
            return self._outro_uitleg()
        sb, m = self.sb, self.merk
        A, B = self.body_end + 0.15, self.totaal
        fade = "\\fad(450,400)"
        self.wordmark(A, B, self.rand, (84 + self.veilig_boven) * self.s, self.tem(40), op_donker=True)
        eyebrow, titel, punten, volgende = self.outro_velden()
        em_e = self.tem(17)
        y = (215 + self.veilig_boven) * self.s
        if self.formaat != "liggend":
            # een staand kader is veel hoger dan de tekst nodig heeft; het blok
            # bovenaan laten plakken geeft een gat in het midden
            kol_v = 2 if self.W >= 1400 else 1
            rijen_v = (len(punten) + kol_v - 1) // kol_v
            blok = ((self.f_label.line_height(self.fs(self.f_label, em_e)) + 52 * self.s if eyebrow else 0)
                    + self.titelhoogte(titel, self.tem(88), self.titelbreedte) + 40 * self.s
                    + rijen_v * (self.f_tekst.line_height(self.fs(self.f_tekst, self.tem(26))) + 18 * self.s)
                    + (110 * self.s if volgende else 0))
            boven = (self.veilig_boven + 150) * self.s
            onderkant = self.H - self.veilig_onder - 110 * self.s - 60 * self.s
            y = boven + max(0.0, (onderkant - boven - blok) / 2)
        if eyebrow:
            self.ev(A, B, f"{{\\an7\\move({self.rand},{y+26},{self.rand},{y},0,650){fade}{self.eyebrow_tags(em_e, 'accent')}}}{esc(self.label_tekst(eyebrow))}", layer=5)
            y += 52 * self.s
        h_t = self._titel_met_accent(A, B, self.rand, y, titel, self.tem(88), self.titelbreedte,
                                     "creme", accent_laatste=True, onderlijn=True)
        y += h_t + 40 * self.s
        # genummerde rij
        em_p = self.tem(26)
        fsv = self.fs(self.f_tekst, em_p)
        fsn = self.fs(self.f_kop, em_p)
        rise = lambda xx, yy, d=0: f"\\move({xx:.1f},{yy+26:.1f},{xx:.1f},{yy:.1f},{d},{d+650})"
        # in een smal kader passen er geen twee kolommen naast elkaar
        kolommen = 2 if self.W >= 1400 else 1
        kol_w = (self.W - 2 * self.rand) / kolommen
        x0, yy = self.rand, y
        lh = self.f_tekst.line_height(fsv) + 18 * self.s
        for i, p in enumerate(punten):
            col = i % kolommen
            row = i // kolommen
            xx, yv = x0 + col * kol_w, yy + row * lh
            d = 300 + i * 100
            self.ev(A, B, f"{{\\an7{rise(xx, yv, d)}{fade}{self.font_tag('kop')}\\fs{fsn:.0f}\\bord0\\shad0{self.c('accent')}}}{i+1:02d}", layer=5)
            self.ev(A, B, f"{{\\an7{rise(xx + 64 * self.s, yv, d)}{fade}{self.font_tag('tekst')}\\fs{fsv:.0f}\\bord0\\shad0{self.c('creme')}}}{esc(p)}", layer=5)
        rows = (len(punten) + kolommen - 1) // kolommen
        y = yy + rows * lh + 30 * self.s
        # "volgende les" (of de CTA) als oranje knop
        band_y = self.H - self.veilig_onder - 110
        if volgende:
            em_k = self.tem(24)
            fsk = self.fs(self.f_label, em_k)
            txt = str(volgende) + "  →"
            kw = self.f_label.width(txt, fsk) + 2 * 30 * self.s
            kh = self.f_label.line_height(fsk) + 2 * 16 * self.s
            ky = min(y, band_y - 40 * self.s - kh)
            self.ev(A, B, f"{{\\an7{rise(self.rand, ky, 700)}{fade}\\bord0\\shad0{self.c('accent')}\\p1}}{rrect(0,0,kw,kh,float(m.get('radius_knop',10)))}{{\\p0}}", layer=5)
            self.ev(A, B, f"{{\\an7{rise(self.rand + 30 * self.s, ky + 16 * self.s, 700)}{fade}{self.font_tag('label')}\\fs{fsk:.0f}\\bord0\\shad0{self.c('wit')}}}{esc(txt)}", layer=6)
        band_txt = self.bandtekst(m.get("band_tekst", m.get("naam", "")), m.get("site", ""),
                                  m.get("outro_band_tekst", ""))
        self.band(A - 0.15, B, band_y, 110 * self.s, m.get("outro_band_achtergrond", "accent"), m.get("outro_band_tekstkleur", "wit"), band_txt)

    def _outro_uitleg(self):
        """Eindkaart voor een uitleg-reel: gecentreerd, als een poster.

        De les-outro is een lijstje linksboven — logisch na een tutorial,
        armoedig na dertig seconden recht in de camera praten. Hier: merkband
        boven en onder als kader, de site klein erboven, één grote kop met de
        accentonderlijn van de site, en de knop die er net iets later inpopt.
        """
        m = self.merk
        A, B = self.body_end + 0.15, self.totaal
        fade = "\\fad(450,400)"
        eyebrow, titel, _punten, volgende = self.outro_velden()
        mid = self.W / 2

        # ── banden boven en onder: het kader van de kaart ──
        # outro_band_tekst is les-taal ("Tot de volgende les") — hier niet
        band_txt = self.bandtekst(m.get("band_tekst", m.get("naam", "")), m.get("site", ""))
        bh = 110 * self.s
        boven_y = self.veilig_boven + 26 * self.s
        onder_y = self.H - self.veilig_onder - bh
        self.band(A - 0.15, B, boven_y, bh, m.get("outro_band_achtergrond", "accent"),
                  m.get("outro_band_tekstkleur", "wit"), band_txt)
        self.band(A - 0.15, B, onder_y, bh, m.get("outro_band_achtergrond", "accent"),
                  m.get("outro_band_tekstkleur", "wit"), band_txt, snelheid=100)

        # ── hoogtes eerst, zodat het blok echt gecentreerd staat ──
        f = self.f_titel
        em_t = self.tem(92)
        fsv = self.fs(f, em_t)
        spf = float(m.get("kop_spatie", 0))
        sp = self.sp(f, em_t, spf)
        maxw = min(self.titelbreedte, self.W - 2 * self.rand)
        lines = wrap_balanced(titel, f, fsv, maxw)
        lh = f.line_height(fsv) * 0.98
        em_e = self.tem(19)
        fse = self.fs(self.f_label, em_e)
        h_eyebrow = (self.f_label.line_height(fse) + 46 * self.s) if eyebrow else 0
        em_k = self.tem(26)
        fsk = self.fs(self.f_label, em_k)
        kh = self.f_label.line_height(fsk) + 2 * 20 * self.s
        h_knop = (kh + 72 * self.s) if volgende else 0
        blok = h_eyebrow + len(lines) * lh + h_knop
        y = boven_y + bh + max(0.0, (onder_y - boven_y - bh - blok) / 2)

        rise = lambda yy, d=0: f"\\move({mid:.1f},{yy+26:.1f},{mid:.1f},{yy:.1f},{d},{d+650})"

        # ── site klein erboven, in caps met ruimte ──
        if eyebrow:
            self.ev(A, B, f"{{\\an8{rise(y, 60)}{fade}{self.eyebrow_tags(em_e, 'accent')}}}"
                          f"{esc(self.label_tekst(eyebrow))}", layer=5)
            y += h_eyebrow

        # ── de kop: gecentreerd, laatste regel accent + onderlijn ──
        for i, line in enumerate(lines):
            laatste = (i == len(lines) - 1)
            kl = "accent" if (laatste and len(lines) > 1) else "creme"
            self.ev(A, B, f"{{\\an8{rise(y, 140 + i * 90)}{fade}{self.font_tag('titel')}"
                          f"\\fs{fsv:.0f}{sp}\\bord0\\shad0{self.c(kl)}}}{esc(line)}", layer=5)
            if laatste:
                woorden = line.split()
                if woorden:
                    lw = f.width(line, fsv) + em_t * spf * len(line)
                    ww = f.width(woorden[-1], fsv) + em_t * spf * len(woorden[-1])
                    ly = y + lh - 6 * self.s
                    lx = mid + lw / 2 - ww
                    self.ev(A, B, f"{{\\an7\\move({lx:.1f},{ly+26:.1f},{lx:.1f},{ly:.1f},{140 + i * 90},{790 + i * 90}){fade}"
                                  f"\\bord0\\shad0{self.c('accent')}\\p1}}m 0 0 l {ww:.0f} 0 l {ww:.0f} {max(6.0, 10 * self.s):.0f} l 0 {max(6.0, 10 * self.s):.0f}{{\\p0}}", layer=5)
            y += lh

        # ── de knop, net iets later ──
        if volgende:
            y += 72 * self.s
            txt = str(volgende) + "  →"
            kw = self.f_label.width(txt, fsk) + 2 * 34 * self.s
            kx = mid - kw / 2
            ky = y
            self.ev(A, B, f"{{\\an7\\move({kx:.1f},{ky+26:.1f},{kx:.1f},{ky:.1f},650,1300){fade}\\bord0\\shad0"
                          f"{self.c('accent')}\\p1}}{rrect(0, 0, kw, kh, float(m.get('radius_knop', 10)))}{{\\p0}}", layer=5)
            self.ev(A, B, f"{{\\an8\\move({mid:.1f},{ky + 20 * self.s + 26:.1f},{mid:.1f},{ky + 20 * self.s:.1f},650,1300){fade}"
                          f"{self.font_tag('label')}\\fs{fsk:.0f}\\bord0\\shad0{self.c('wit')}}}{esc(txt)}", layer=6)

    # ── oude "gradient"-stijl (zachte look), blijft beschikbaar ──
    def _blok_tekst(self, start, end, eyebrow, titel, pills, onder_links=None, onder_rechts=None):
        m = self.merk
        wit = self.c("wit")
        bx, by, bw, bh = 160, 160, 1600, 760
        x0 = bx + 100
        fade = "\\fad(450,400)"
        rise = lambda x, y, d=0: f"\\move({x:.1f},{y+26:.1f},{x:.1f},{y:.1f},{d},{d+650})"
        fs_t = self.fs(self.f_titel, 82)
        lines_pre = wrap(titel, self.f_titel, fs_t, bw - 200)
        inhoud_h = (70 if eyebrow else 0) + len(lines_pre) * self.f_titel.line_height(fs_t) + 50 + (64 if pills else 0) + (60 if (onder_links or onder_rechts) else 0)
        y = by + max(80, (bh - inhoud_h) / 2 - 20)
        if eyebrow:
            self.ev(start, end, f"{{\\an7{rise(x0, y)}{fade}{self.font_tag('label')}\\fs{self.fs(self.f_label, 26):.0f}\\bord0\\shad0{wit}}}— {esc(eyebrow)}", layer=5)
            y += 70
        lh = self.f_titel.line_height(fs_t)
        body = "\\N".join(esc(l) for l in lines_pre)
        self.ev(start, end, f"{{\\an7{rise(x0, y, 120)}{fade}{self.font_tag('titel')}\\fs{fs_t:.0f}\\fsp-2\\bord0\\shad0{wit}}}{body}", layer=5)
        y += len(lines_pre) * lh + 50
        fs_p = self.fs(self.f_label, 23)
        px, py = x0, min(y, by + bh - 200)
        for i, p in enumerate(pills or []):
            txt = str(p)
            pw = self.f_label.width(txt, fs_p) + 2 * 26
            ph = self.f_label.line_height(fs_p) + 2 * 12
            if px + pw > bx + bw - 100:
                px = x0
                py += ph + 14
            d = 300 + i * 110
            self.ev(start, end, f"{{\\an7{rise(px, py, d)}{fade}\\bord2\\shad0{self.c('wit', 0.82)}{self.c3('wit')}\\p1}}{rrect(0,0,pw,ph,ph/2)}{{\\p0}}", layer=5)
            self.ev(start, end, f"{{\\an7{rise(px+26, py+12, d)}{fade}{self.font_tag('label')}\\fs{fs_p:.0f}\\bord0\\shad0{wit}}}{esc(txt)}", layer=6)
            px += pw + 14
        if onder_links:
            self.ev(start, end, f"{{\\an1{rise(x0, by+bh-70, 500)}{fade}{self.font_tag('kop')}\\fs{self.fs(self.f_kop, 28):.0f}\\bord0\\shad0{wit}}}{esc(onder_links)}", layer=5)
        if onder_rechts:
            self.ev(start, end, f"{{\\an3{rise(bx+bw-100, by+bh-70, 500)}{fade}{self.font_tag('label')}\\fs{self.fs(self.f_label, 25):.0f}\\bord0\\shad0{wit}}}{esc(onder_rechts)}", layer=5)

    def _intro_gradient(self):
        sb, m = self.sb, self.merk
        eyebrow = " · ".join(x for x in [m.get("site"), None if self.uitleg else sb.get("reeks")] if x)
        self._blok_tekst(0.0, self.intro_d - 0.35, eyebrow, str(sb.get("titel", "")),
                         [] if self.uitleg else (sb.get("intro_punten") or []))

    def _outro_gradient(self):
        sb, m = self.sb, self.merk
        A, B = self.body_end, self.totaal
        eyebrow, titel, punten, volgende = self.outro_velden()
        self._blok_tekst(A + 0.2, B, eyebrow, titel, punten,
                         onder_links=volgende, onder_rechts=m.get("site"))

    # ═══════════════════════════════════════════════════════════════
    #  ASS schrijven
    # ═══════════════════════════════════════════════════════════════
    def schrijf_ass(self, path):
        m = self.merk
        hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.W}
PlayResY: {self.H}
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Basis,{self.fontnaam['kop']},40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [hdr]
        for layer, a, b, text in sorted(self.events, key=lambda e: (e[1], e[0])):
            lines.append(f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},Basis,,0,0,0,,{text}\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)

    # ═══════════════════════════════════════════════════════════════
    #  Achtergrond intro/outro (enkel voor de gradient-stijl) via ffmpeg
    # ═══════════════════════════════════════════════════════════════
    def maak_achtergrond(self, path):
        if os.path.exists(path):
            return path
        m = self.merk
        c0, c1 = self.kleur(m.get("gradient_van", "perzik")), self.kleur(m.get("gradient_naar", "roze"))
        creme = self.kleur("creme")
        bw, bh, r = 1600, 760, 42
        mask = (f"255*clip(0.5+{r}-hypot(max(abs(X-{bw/2})-{bw/2-r},0),"
                f"max(abs(Y-{bh/2})-{bh/2-r},0)),0,1)")
        fc = (f"[1]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask}'[blk];"
              f"[1]format=rgba,geq=r=0:g=0:b=0:a='({mask})*0.16',pad=iw+120:ih+120:60:60:color=black@0,gblur=sigma=22[sh];"
              f"[0][sh]overlay=100:112[bg];[bg][blk]overlay=160:160:format=auto")
        cmd = [FF, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", f"color=c={creme}:s={W}x{H}:d=1",
               "-f", "lavfi", "-i", f"gradients=s={bw}x{bh}:c0={c0}:c1={c1}:x0=0:y0=0:x1={bw}:y1={bh}:nb_colors=2:d=1",
               "-filter_complex", fc, "-frames:v", "1", path]
        r_ = subprocess.run(cmd, capture_output=True, text=True)
        if r_.returncode != 0:
            die("achtergrond maken mislukt:\n" + r_.stderr)
        return path

    # ═══════════════════════════════════════════════════════════════
    #  ffmpeg-opdracht
    # ═══════════════════════════════════════════════════════════════
    def zoom_expr(self):
        if not self.zooms:
            return None
        T = f"(in/{FPS})"
        zparts, xparts, yparts = [], [], []
        for t0, t1, z, cx, cy in self.zooms:
            s_in = f"st(0,clip(({T}-{t0:.3f})/{RAMP},0,1))*ld(0)*(3-2*ld(0))"
            s_out = f"st(1,clip(({T}-{t1-RAMP:.3f})/{RAMP},0,1))*ld(1)*(3-2*ld(1))"
            zparts.append(f"({z-1:.4f})*(({s_in})-({s_out}))")
            xparts.append(f"between({T},{t0:.3f},{t1:.3f})*clip({cx:.1f}-iw/zoom/2,0,iw-iw/zoom)")
            yparts.append(f"between({T},{t0:.3f},{t1:.3f})*clip({cy:.1f}-ih/zoom/2,0,ih-ih/zoom)")
        zexpr = "1+" + "+".join(zparts)
        xexpr = "+".join(xparts)
        yexpr = "+".join(yparts)
        return f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1:s={self.W}x{self.H}:fps={FPS}"

    def _bg_input(self, welke, duur, bg_path):
        """Input-argumenten voor de intro/outro-achtergrond."""
        if self.stijl == "editorial":
            kl = self.kleur(self.merk.get(f"{welke}_achtergrond", "creme" if welke == "intro" else "ink"))
            return ["-f", "lavfi", "-t", f"{duur:.3f}", "-i", f"color=c={kl}:s={self.W}x{self.H}:r={FPS}"]
        return ["-loop", "1", "-framerate", str(FPS), "-t", f"{duur:.3f}", "-i", bg_path]

    def ffmpeg_cmd(self, ass_path, out_path, bg_path):
        fade_col = "0x" + self.kleur(self.kaderkleur()).lstrip("#")
        inputs = [FF, "-y", "-hide_banner", "-loglevel", "warning", "-stats"]
        fc = []
        kaderkl = self.kleur(self.kaderkleur())
        nin = 0
        clip_v, clip_a = [], []
        # Elke clip wordt eerst op zichzelf naar het uitvoerkader gebracht en
        # daarna plakken we ze aan elkaar. Zo mag clip 1 een breed scherm zijn
        # en clip 2 een staande selfie: allebei komen ze goed in beeld, en
        # alles wat erna komt (knippen, versnellen, zoomen, overlays) werkt op
        # één doorlopende tijdlijn alsof het altijd één opname was.
        for c in self.clips:
            inputs += ["-ss", f"{c.van:.3f}", "-t", f"{c.duur:.3f}", "-i", c.pad]
            vi = nin; nin += 1
            fc.append(f"[{vi}:v]fps={FPS},{c.kader.vf(kaderkl)}{self.look_vf()},format=yuv420p,"
                      f"setpts=PTS-STARTPTS[k{vi}]")
            if c.audio:
                fc.append(f"[{vi}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                          f"channel_layouts=stereo,asetpts=PTS-STARTPTS[ka{vi}]")
                clip_v.append(f"[k{vi}]"); clip_a.append(f"[ka{vi}]")
            else:
                # een schermopname zonder microfoon: stilte in de plaats, anders
                # kan ffmpeg de clips niet aan elkaar zetten
                inputs += ["-f", "lavfi", "-t", f"{c.duur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                ai = nin; nin += 1
                fc.append(f"[{ai}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                          f"channel_layouts=stereo[ka{vi}]")
                clip_v.append(f"[k{vi}]"); clip_a.append(f"[ka{vi}]")
        if len(self.clips) > 1:
            samen = "".join(v + a for v, a in zip(clip_v, clip_a))
            fc.append(f"{samen}concat=n={len(self.clips)}:v=1:a=1[bron_v][bron_a]")
            bron_v, bron_a = "[bron_v]", "[bron_a]"
        else:
            bron_v, bron_a = clip_v[0], clip_a[0]

        segs = self.tl.segs
        N = len(segs)
        zp = self.zoom_expr()
        fc.append(f"{bron_v}{zp or 'null'},split={N}" + "".join(f"[s{i}]" for i in range(N)))
        fc.append(f"{bron_a}asplit={N}" + "".join(f"[as{i}]" for i in range(N)))
        concat_in = []
        if self.intro_on:
            inputs += self._bg_input("intro", self.intro_d, bg_path)
            vi = nin; nin += 1
            inputs += ["-f", "lavfi", "-t", f"{self.intro_d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            ai = nin; nin += 1
            fc.append(f"[{vi}:v]format=yuv420p,scale={self.W}:{self.H},setsar=1,fade=t=in:st=0:d=0.4:color={fade_col},"
                      f"fade=t=out:st={self.intro_d-0.45:.3f}:d=0.45:color={fade_col}[vi]")
            fc.append(f"[{ai}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ai]")
            concat_in.append("[vi][ai]")
        for i, (a, b, f) in enumerate(segs):
            v = f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{f:g}"
            if i == 0 and self.intro_on:
                v += f",fade=t=in:st=0:d=0.4:color={fade_col}"
            if i == N - 1 and self.outro_on:
                d = (b - a) / f
                v += f",fade=t=out:st={max(0, d-0.5):.3f}:d=0.5:color={fade_col}"
            fc.append(v + f"[v{i}]")
            au = f"[as{i}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS"
            if f != 1.0:
                rest = f
                while rest > 2.0:
                    au += ",atempo=2"
                    rest /= 2.0
                au += f",atempo={rest:.4f},volume=0.15"
            fc.append(au + f"[a{i}]")
            concat_in.append(f"[v{i}][a{i}]")
        if self.outro_on:
            inputs += self._bg_input("outro", self.outro_d, bg_path)
            vo = nin; nin += 1
            inputs += ["-f", "lavfi", "-t", f"{self.outro_d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            ao = nin; nin += 1
            fc.append(f"[{vo}:v]format=yuv420p,scale={self.W}:{self.H},setsar=1,fade=t=in:st=0:d=0.5:color={fade_col},"
                      f"fade=t=out:st={self.outro_d-0.6:.3f}:d=0.6:color={fade_col}[vo]")
            fc.append(f"[{ao}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ao]")
            concat_in.append("[vo][ao]")
        n_all = len(concat_in)
        fc.append("".join(concat_in) + f"concat=n={n_all}:v=1:a=1[vc][ac]")
        post = f"fps={FPS}"
        if self.preview:
            # de lange zijde naar 1280, de verhouding behouden — een vaste
            # 1280x720 zou een staande reel plat drukken
            f = 1280 / max(self.W, self.H)
            pw, ph = int(round(self.W * f)) // 2 * 2, int(round(self.H * f)) // 2 * 2
            post += f",scale={pw}:{ph}"
        fontsdir = os.path.join(HERE, "fonts")
        ass_esc = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        fd_esc = fontsdir.replace(":", "\\:")
        fc.append(f"[vc]{post},ass=filename='{ass_esc}':fontsdir='{fd_esc}'[vout]")
        fc.append("[ac]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        cmd = inputs + ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]"]
        codec = str(self.sb.get("codec", "auto"))
        if codec != "auto" and not self.preview:
            # het storyboard mag een encoder afdwingen, maar alleen als deze
            # ffmpeg hem echt heeft — anders faalt de render pas na de opbouw
            wens = {"videotoolbox": "h264_videotoolbox", "x264": "libx264",
                    "nvenc": "h264_nvenc", "qsv": "h264_qsv"}.get(codec, codec)
            if wens in omgeving.mogelijkheden(FF)["encoders"]:
                if wens == "libx264":
                    cmd += ["-c:v", wens, "-preset", "medium", "-crf", str(self.sb.get("crf", 19)),
                            "-profile:v", "high", "-pix_fmt", "yuv420p"]
                else:
                    cmd += ["-c:v", wens, "-b:v", str(self.sb.get("bitrate", "9M")), "-profile:v", "high"]
            else:
                self.waarschuwingen.append(
                    f"codec '{codec}' bestaat niet in deze ffmpeg — automatische keuze gebruikt")
                cmd += omgeving.kies_encoder(FF, False, self.sb.get("bitrate", "9M"), self.sb.get("crf", 19))
        else:
            cmd += omgeving.kies_encoder(FF, self.preview,
                                         self.sb.get("bitrate", "9M"), self.sb.get("crf", 19))
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
        return cmd

    # ═══════════════════════════════════════════════════════════════
    def bouw_hook(self):
        """Eén regel die meteen de belofte doet, over het beeld heen.

        Een reel moet in de eerste seconde duidelijk maken waarom je blijft
        kijken, en dat lukt niet met een kaart waar nog geen beweging op staat.
        Daarom zetten we de hook op het beeld zelf: bij een brede opname in de
        merkbalk erboven, en anders over het beeld met een vlak eronder zodat
        hij leesbaar blijft.
        """
        tekst = self.sb.get("hook")
        if not tekst:
            return
        duur_in = self.sb.get("hook_duur", 2.6)
        A = self.body_start
        if str(duur_in).strip().lower() == "heel":
            # b-roll: de tekst ís de inhoud, dus hij blijft de hele video staan
            B = self.body_end
        else:
            B = min(A + float(duur_in), self.body_end)
        if B - A < 0.4:
            return
        m = self.merk
        f = self.f_titel
        em = self.tem(76)
        fsv = self.fs(f, em)
        lines = wrap_balanced(str(tekst), f, fsv, self.W - 2 * self.marge - 40)
        lh = f.line_height(fsv) * 0.98
        blok = len(lines) * lh
        bx, by, bw, bh = self.kader.beeld
        ruimte = by - self.veilig_boven - self.marge
        op_balk = ruimte >= blok + 60 * self.s
        if op_balk:
            y = self.veilig_boven + self.marge + max(0.0, (ruimte - blok) / 2)
            kl = "creme" if is_donker(self.kleur(self.kaderkleur())) else "ink"
        else:
            y = max(self.veilig_boven + self.marge, by + 40 * self.s)
            kl = "creme"
            pad = 22 * self.ts
            wmax = max(f.width(l, fsv) for l in lines)
            self.ev(A, B, f"{{\\an7\\pos({self.W/2 - wmax/2 - pad:.1f},{y - pad:.1f})\\fad(200,260)"
                          f"\\bord0\\shad0{self.c('ink', 0.12)}\\p1}}"
                          f"{rrect(0, 0, wmax + 2*pad, blok + 2*pad, float(m.get('radius_kaart', 16)))}{{\\p0}}",
                    layer=44)
        sp = self.sp(f, em, float(m.get("kop_spatie", 0)))
        self.bezet_boven.append((A, B, y + blok + 28 * self.s))
        for i, regel in enumerate(lines):
            # laatste regel in de accentkleur, net als op de titelkaart
            k = "accent" if (i == len(lines) - 1 and len(lines) > 1) else kl
            pop = "\\fscx104\\fscy104\\t(0,260,\\fscx100\\fscy100)"
            self.ev(A, B, f"{{\\an8\\pos({self.W/2:.1f},{y + i*lh:.1f})\\fad(180,260){pop}"
                          f"{self.font_tag('titel')}\\fs{fsv:.0f}{sp}\\bord0\\shad0{self.c(k)}}}{esc(regel)}",
                    layer=45)

    def bouw_alles(self):
        # volgorde telt: hook en stapkaarten claimen eerst hun plek in de band
        # boven het beeld, daarna schuiven tip- en promptkaarten eronder
        self.bouw_ondertitels()
        self.bouw_hook()
        self.bouw_stappen()
        self.bouw_highlights()
        self.bouw_kaarten_rechts()
        self.bouw_versnelchips()
        self.bouw_intro()
        self.bouw_outro()

    def rapport(self):
        tl = self.tl
        print(f"Bron: {os.path.basename(self.bron)}  {ftime(self.duur)}  ({self.src_w}x{self.src_h})  · merk {self.merk.get('naam')} ({self.stijl})")
        print(f"Formaat: {self.formaat} {self.W}x{self.H} · beeld {self.kader.modus} "
              f"({self.kader.beeld[2]:.0f}x{self.kader.beeld[3]:.0f} op y={self.kader.beeld[1]:.0f})")
        if len(self.clips) > 1:
            print(f"Montage: {len(self.clips)} clips aan elkaar")
            for i, c in enumerate(self.clips, 1):
                stuk = "" if (c.van == 0 and abs(c.tot - c.bestandsduur) < 0.05) \
                    else f"  (stuk {ftime(c.van)}–{ftime(c.tot)})"
                geluid = "" if c.audio else "  · zonder geluid"
                print(f"  {i}. {ftime(c.start)}–{ftime(c.einde)}  {os.path.basename(c.pad)}"
                      f"  {c.src_w}x{c.src_h} {c.kader.modus}{stuk}{geluid}")
        print(f"Uitvoer: {ftime(self.totaal)}  (intro {self.intro_d:g}s + lichaam {ftime(tl.totaal)} + outro {self.outro_d:g}s)")
        if self.knips:
            print("Geknipt: " + ", ".join(f"{ftime(a)}–{ftime(b)}" for a, b in self.knips))
        if self.versnels:
            print("Versneld: " + ", ".join(f"{ftime(a)}–{ftime(b)} ×{f:g}" for a, b, f in self.versnels))
        print(f"Overlays: {len(self.events)} ASS-events, {getattr(self, 'n_subs', 0)} ondertitels, "
              f"{len(self.sb.get('stappen') or [])} stappen, {len(self.sb.get('highlights') or [])} highlights "
              f"({len(self.zooms)} met zoom), {len(self.sb.get('tips') or [])} tips, {len(self.sb.get('prompts') or [])} prompts")
        for w in self.waarschuwingen:
            print(f"  ! {w}")


# ═══════════════════════════════════════════════════════════════════
#  Commando's
# ═══════════════════════════════════════════════════════════════════
def cmd_render(args):
    venster = None
    if args.van is not None or args.tot is not None:
        venster = (ptime(args.van) if args.van is not None else 0.0,
                   ptime(args.tot) if args.tot is not None else 10 ** 9)
    b = Bouwer(args.les, preview=args.preview, venster=venster, zonder_intro=args.zonder_intro)
    b.bouw_alles()
    naam = os.path.basename(b.lesdir.rstrip("/"))
    suffix = "_preview" if args.preview else ""
    if venster:
        suffix += f"_{int(venster[0])}-{int(min(venster[1], b.duur))}"
    out_path = args.uit or os.path.join(b.uitdir, f"{naam}{suffix}.mp4")
    ass_path = os.path.join(b.uitdir, f"{naam}{suffix}.ass")
    bg_path = os.path.join(b.uitdir, f"achtergrond_{b.merk.get('naam','merk')}.png")
    b.schrijf_ass(ass_path)
    if (b.intro_on or b.outro_on) and b.stijl != "editorial":
        b.maak_achtergrond(bg_path)
    b.rapport()
    cmd = b.ffmpeg_cmd(ass_path, out_path, bg_path)
    with open(os.path.join(b.uitdir, "laatste_ffmpeg.txt"), "w") as fh:
        fh.write(" ".join(f"'{c}'" if " " in c or ";" in c else c for c in cmd) + "\n")
    if args.alleen_ass:
        print(f"→ ASS geschreven: {ass_path}")
        return
    print(f"→ renderen naar {out_path} …")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        die("ffmpeg gaf een fout (zie hierboven). De opdracht staat in uit/laatste_ffmpeg.txt")
    size = os.path.getsize(out_path) / 1e6
    print(f"✓ klaar: {out_path}  ({size:.0f} MB, {ftime(probe_duration(out_path))})")


def cmd_check(args):
    b = Bouwer(args.les)
    b.bouw_alles()
    b.rapport()
    print("\nStappen (bron → uitvoer):")
    for i, s in enumerate(b.sb.get("stappen") or []):
        t = ptime(s["van"])
        print(f"  {i+1:>2}. {ftime(t):>6} → {ftime(b.T(t)):>6}  {s.get('titel','')}")
    if b.zooms:
        print("Zooms:")
        for t0, t1, z, cx, cy in b.zooms:
            print(f"  {ftime(t0)}–{ftime(t1)}  ×{z:g} rond ({cx:.0f},{cy:.0f})")


def cmd_frame(args):
    lesdir = os.path.abspath(args.les)
    # via de Bouwer, zodat een moment op de gemonteerde tijdlijn bij de juiste
    # clip terechtkomt in plaats van altijd bij het eerste bestand
    b = Bouwer(lesdir)
    t = ptime(args.tijd)
    c = b.clip_op(max(0.0, t))
    bron, t_lokaal = c.pad, c.lokaal(t)
    sb = b.sb
    os.makedirs(os.path.join(lesdir, "frames"), exist_ok=True)
    out = os.path.join(lesdir, "frames", f"t{int(t)}{'_raster' if args.raster else ''}.png")
    creme = laad_merk((sb or {}).get("merk", STANDAARD_MERK)).get("creme", "#fff8f2")
    vf = normaliseer_vf(creme)
    if args.raster:
        # lijnen om de 100 px + cijfers, zodat je coördinaten kunt aflezen
        parts = [vf]
        for x in range(100, W, 100):
            parts.append(f"drawbox=x={x}:y=0:w=1:h={H}:color=red@0.5")
            parts.append(f"drawtext=text='{x}':x={x+3}:y=4:fontsize=18:fontcolor=red:box=1:boxcolor=white@0.6")
        for y in range(100, H, 100):
            parts.append(f"drawbox=x=0:y={y}:w={W}:h=1:color=red@0.5")
            parts.append(f"drawtext=text='{y}':x=4:y={y+3}:fontsize=18:fontcolor=red:box=1:boxcolor=white@0.6")
        vf = ",".join(parts)
    r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t_lokaal:.3f}", "-i", bron,
                        "-frames:v", "1", "-vf", vf, out])
    if r.returncode != 0:
        die("frame maken mislukt")
    print(f"✓ {out}")


def maak_montage_audio(lesdir, clips):
    """Eén geluidsbestand over alle clips samen.

    Whisper en de stiltedetectie kijken naar de hele les in één keer. Bij
    meerdere opnames moeten die dus het aaneengesloten geluid horen, met de
    juiste tijden — anders staan je ondertitels straks bij de verkeerde clip.
    Clips zonder microfoon leveren stilte, precies zo lang als ze duren.
    """
    uit = os.path.join(lesdir, ".montage_audio.m4a")
    inputs, delen, nin = [], [], 0
    for c in clips:
        pad = os.path.join(lesdir, c)
        d = probe_duration(pad)
        if heeft_audio(pad):
            inputs += ["-i", pad]
        else:
            inputs += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        delen.append(f"[{nin}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                     f"channel_layouts=stereo,atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{nin}]")
        nin += 1
    filt = ";".join(delen) + ";" + "".join(f"[a{i}]" for i in range(nin)) + f"concat=n={nin}:v=0:a=1[uit]"
    r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + inputs
                       + ["-filter_complex", filt, "-map", "[uit]", "-c:a", "aac", uit])
    if r.returncode != 0:
        print("  ! het gezamenlijke geluidsspoor kon niet gemaakt worden — "
              "ondertitels en stiltes worden op de eerste clip gebaseerd")
        return os.path.join(lesdir, clips[0])
    return uit


def draai_whisper_met_voortgang(cmd):
    """Whisper laten doorpraten in plaats van hem te smoren.

    Vroeger ging alle whisper-uitvoer naar DEVNULL en leek een lange
    transcriptie minutenlang bevroren: in de studio stond de balk op 0% en
    de log stond stil — "het werkt niet", terwijl het gewoon aan het werk
    was. Nu stroomt de herkende tekst door naar de log, en drukken we elke
    tijdstempel ook af als `time=…` — hetzelfde formaat als ffmpeg, zodat
    de voortgangslezer van de studio er niets nieuws voor hoeft te kennen.
    """
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace", bufsize=1)
    for regel in p.stdout:
        regel = regel.rstrip()
        m = re.match(r"^\[(\d+):(\d\d):(\d\d)\.(\d)\d* --> ", regel)
        if m:
            print(f"time={m.group(1)}:{m.group(2)}:{m.group(3)}.{m.group(4)}", flush=True)
            tekst = regel.split("]", 1)[-1].strip()
            if tekst:
                print("  " + tekst, flush=True)
    if p.wait() != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)


def cmd_nieuw(args):
    naam = re.sub(r"[^a-z0-9\-]+", "-", args.naam.lower()).strip("-")
    lesdir = os.path.join(HERE, "lessen", naam)
    if os.path.exists(lesdir) and not args.overschrijf:
        die(f"{lesdir} bestaat al (gebruik --overschrijf om transcript/storyboard opnieuw te maken)")
    os.makedirs(lesdir, exist_ok=True)
    # Meerdere opnames mogen: ze worden in de volgorde waarin je ze noemt aan
    # elkaar geplakt tot één doorlopende tijdlijn.
    bronnen = [os.path.abspath(b) for b in (args.bron if isinstance(args.bron, list) else [args.bron])]
    for b in bronnen:
        if not os.path.exists(b):
            die(f"bron niet gevonden: {b}")
        if not heeft_beeld(b):
            die(f"{os.path.basename(b)} bevat geen beeld, alleen geluid.\n"
                "  Kies je schermopname of je camerabeeld (.mp4, .mov) —\n"
                "  uit een audiobestand valt geen video te maken.")
    clips = []
    for i, bron_in in enumerate(bronnen, 1):
        ext = os.path.splitext(bron_in)[1].lower() or ".mp4"
        naam_in = "bron" + ext if len(bronnen) == 1 else f"clip{i}{ext}"
        doel = os.path.join(lesdir, naam_in)
        if not os.path.exists(doel):
            gelinkt = False
            if args.link:
                try:
                    os.symlink(bron_in, doel)
                    gelinkt = True
                except (OSError, NotImplementedError) as e:
                    # Windows staat symlinks alleen toe met extra rechten
                    print(f"  ! symlink lukte niet ({e}) — de opname wordt gekopieerd")
            if not gelinkt:
                print(f"→ kopieer {os.path.basename(bron_in)} ({os.path.getsize(bron_in)/1e6:.0f} MB) …")
                shutil.copy2(bron_in, doel)
        clips.append(naam_in)
    bron = os.path.join(lesdir, clips[0])
    # Whisper en de stiltedetectie luisteren naar álle clips samen, zodat de
    # tijden op de gemonteerde tijdlijn kloppen. Het beeld blijft per clip.
    audio_bron = bron
    if len(clips) > 1:
        print(f"→ {len(clips)} clips: " + ", ".join(clips))
        audio_bron = maak_montage_audio(lesdir, clips)
    duur = sum(probe_duration(os.path.join(lesdir, c)) for c in clips)
    print(f"→ duur {ftime(duur)}")

    # ── transcriberen ──
    ruw = os.path.join(lesdir, "transcript_ruw.srt")
    if not os.path.exists(ruw) or args.overschrijf:
        model = omgeving.zoek_whisper_model()
        whisper = omgeving.zoek_whisper()
        if not whisper or not model:
            wat = "whisper-cli" if not whisper else f"het model {omgeving.MODEL_NAAM}"
            print(f"  ! {wat} niet gevonden — transcriptie overgeslagen.\n"
                  f"    Installeren:  {omgeving.hint('whisper' if not whisper else 'model')}\n"
                  f"    Daarna dit commando opnieuw met --overschrijf.\n"
                  f"    Of schrijf zelf lessen/{naam}/ondertitels.srt — de rest werkt gewoon.")
        elif not heeft_audio(audio_bron):
            print("  ! geen geluid in de opname — transcriptie overgeslagen.\n"
                  f"    Schrijf zelf lessen/{naam}/ondertitels.srt als je ondertitels wil.")
        else:
            wav = os.path.join(lesdir, ".audio16k.wav")
            subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", audio_bron, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
            print("→ transcriberen met whisper (dit duurt even) …")
            base = os.path.join(lesdir, "transcript_ruw")
            prompt = (args.woordenlijst
                      or omgeving.instelling("woordenlijst")
                      or "Een tutorial met eigennamen van producten, menu's en knoppen.")
            draai_whisper_met_voortgang([whisper, "-m", model, "-l", args.taal, "-t", "8", "--prompt", prompt, "-osrt", "-of", base, "-f", wav])
            os.remove(wav)
    subs = os.path.join(lesdir, "ondertitels.srt")
    if os.path.exists(ruw) and (not os.path.exists(subs) or args.overschrijf):
        rules = load_woordenboek(os.path.join(HERE, "woordenboek.conf"))
        cues = read_srt(ruw)
        with open(subs, "w", encoding="utf-8") as fh:
            for i, (a, b, t) in enumerate(cues, 1):
                fh.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{apply_woordenboek(t, rules)}\n\n")
        print(f"→ ondertitels.srt ({len(cues)} regels, woordenboek toegepast) — nalezen!")

    # ── stiltes → versnel-voorstellen ──
    stiltes = detecteer_stiltes(audio_bron, min_duur=float(args.stilte))
    # ── contactsheet ──
    fr = os.path.join(lesdir, "frames")
    os.makedirs(fr, exist_ok=True)
    for i, c in enumerate(clips, 1):
        contact = os.path.join(fr, "contact.jpg" if len(clips) == 1 else f"contact{i}.jpg")
        if os.path.exists(contact):
            continue
        cd = probe_duration(os.path.join(lesdir, c))
        # Het interval volgt de lengte van de clip. Vast om de 30 seconden
        # bemonsteren leverde bij een korte opname te weinig beelden op voor
        # het raster, en dan maakte ffmpeg helemaal niets.
        interval = max(1.0, cd / 12)
        aantal = max(1, min(24, int(cd / interval) or 1))
        cols = min(4, aantal)
        rijen = math.ceil(aantal / cols)
        r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", os.path.join(lesdir, c),
                            "-vf", f"fps=1/{interval:.3f},scale=480:-1,"
                                   f"drawtext=text='%{{pts\\:hms}}':x=8:y=8:fontsize=22:"
                                   f"fontcolor=white:box=1:boxcolor=black@0.5,"
                                   f"tile={cols}x{rijen}:padding=4:margin=4",
                            "-frames:v", "1", contact], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  ! overzichtsbeeld voor {c} kon niet gemaakt worden")
    print(f"→ overzicht: frames/contact*.jpg" if len(clips) > 1 else "→ overzicht: frames/contact.jpg")

    # ── storyboard ──
    sbp = os.path.join(lesdir, "storyboard.yaml")
    if not os.path.exists(sbp) or args.overschrijf:
        tpl = open(os.path.join(HERE, "storyboard_voorbeeld.yaml"), encoding="utf-8").read()
        versnel = ""
        for a, b in stiltes:
            a2, b2 = a + 0.7, b - 0.7
            if b2 - a2 >= 3:
                versnel += f"  - {{ van: {ftime(a2)}, tot: {ftime(b2)}, factor: 8 }}\n"
        if len(clips) > 1:
            tpl = tpl.replace("bron: bron.mp4\n",
                              "clips:\n" + "".join(f"  - bestand: {c}\n" for c in clips))
        elif clips[0] != "bron.mp4":
            tpl = tpl.replace("bron: bron.mp4", f"bron: {clips[0]}")
        tpl = tpl.replace("__TITEL__", args.titel or naam.replace("-", " ").title())
        # het sjabloon noemt het neutrale merk; een nieuwe les hoort te
        # vertrekken van het standaardmerk uit instellingen.yaml
        tpl = tpl.replace("merk: standaard", f"merk: {STANDAARD_MERK}", 1)
        tpl = tpl.replace("__VERSNEL__", versnel or "  # - { van: 7:19, tot: 7:34, factor: 8 }\n")
        tpl = tpl.replace("__DUUR__", ftime(duur))
        open(sbp, "w", encoding="utf-8").write(tpl)
        print(f"→ storyboard.yaml aangemaakt met {len([1 for a,b in stiltes if b-a-1.4>=3])} versnel-voorstellen")
    print(f"\n✓ klaar om aan te werken: {lesdir}\n"
          f"  1. lees ondertitels.srt na\n"
          f"  2. vul storyboard.yaml in (stappen, highlights, tips, prompts)\n"
          f"  3. ./reelstudio.sh render {naam} --preview   en daarna zonder --preview")


PROEF_STORYBOARD = """titel: Een proefrender|die alles aanraakt
reeks: Proef
merk: {merk}
formaat: {formaat}
bron: bron.mp4
intro_punten: [Intro, Highlight, Kaart]
outro_titel: Als je dit ziet, werkt je installatie.
outro_punten: [Intro en outro, Ondertitels, Highlights]
outro_volgende: "Nu je eigen opname"
webcam: [1338, 824, 404, 228]

stappen:
  - van: 0:00
    titel: Wat we gaan maken
    nummer: 0
    label: Intro
  - van: 0:06
    titel: Kijk naar het gemarkeerde vak

highlights:
  - van: 0:07
    tot: 0:11
    gebied: [700, 300, 520, 300]
    tekst: Hier gebeurt het

tips:
  - van: 0:02
    tekst: Een tip verschijnt rechtsboven.
    duur: 5

prompts:
  - van: 0:13
    nummer: 1
    titel: Een promptkaart

versnel:
  - {{ van: 0:15, tot: 0:19, factor: 4 }}
"""

PROEF_SRT = """1
00:00:00,500 --> 00:00:04,000
Dit is een proefrender van Reelstudio.

2
00:00:04,500 --> 00:00:08,000
Als je dit leest, tekent libass de ondertitels correct.

3
00:00:08,500 --> 00:00:13,000
En dit is een langere regel die automatisch over twee regels verdeeld wordt, met een leesteken in het midden.
"""


# ═══════════════════════════════════════════════════════════════════
#  Merk-wizard
# ═══════════════════════════════════════════════════════════════════
MERK_SJABLOON = """# ══════════════════════════════════════════════════════════════════
#  Merkstijl "{naam}" — gemaakt met ./reelstudio.sh merk nieuw
#
#  Alles wat hier niet staat krijgt een verstandige standaardwaarde, en
#  de grijstinten worden afgeleid van je drie kleuren. Je mag dus gerust
#  regels bijzetten of weghalen. Kijk het resultaat na met:
#
#      ./reelstudio.sh merk toon {naam}
#
#  Gebruik dit merk in een les door in storyboard.yaml te zetten:
#      merk: {naam}
# ══════════════════════════════════════════════════════════════════
naam: {naam}
site: {site}
wordmark: {wordmark}            # linksboven in de intro en de outro
wordmark_accent: {accent_deel}          # dit stuk krijgt de accentkleur
stijl: editorial                # editorial (strak) | gradient (zacht verloop)

# ── kleuren ──────────────────────────────────────────────────────
# Deze drie bepalen alles; de rest (grijs, lijntjes, gedempte tekst)
# wordt eruit afgeleid. Wil je die toch zelf zetten, voeg dan regels
# toe zoals  grijs: "#5c6470"
creme: "{creme}"               # achtergrond van de intro
ink: "{ink}"               # koppen, knoppen, de donkere outro
accent: "{accent}"               # accentwoord, randen, knoppen

# ── lettertypes ──────────────────────────────────────────────────
# Een keten: het eerste lettertype dat op de computer staat wordt
# gebruikt. Zet je eigen .ttf in fonts/ en schrijf zijn volledige naam
# vooraan. Controleer met:  ./reelstudio.sh dokter --merk {naam}
font_titel: {font_zwaar}
font_kop: {font_zwaar}
font_label: {font_midden}
font_tekst: {font_gewoon}
font_ondertitel: {font_midden}

# ── loopband onderaan de intro en de outro ───────────────────────
band_tekst: {band_tekst}
outro_band_tekst: {outro_band_tekst}
"""


def vraag(tekst, standaard="", uitleg=None):
    """Eén vraag; enter houdt de standaardwaarde."""
    if uitleg:
        print(f"    {uitleg}")
    toon = f" [{standaard}]" if standaard else ""
    try:
        antwoord = input(f"  {tekst}{toon}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        die("afgebroken — er is niets weggeschreven")
    return antwoord or standaard


def lees_kleur(tekst, standaard, uitleg=None):
    """Vraagt een hexkleur en blijft vragen tot ze klopt."""
    while True:
        v = vraag(tekst, standaard, uitleg).strip()
        if not v.startswith("#"):
            v = "#" + v
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            return v.lower()
        if re.fullmatch(r"#[0-9a-fA-F]{3}", v):   # #abc → #aabbcc
            return "#" + "".join(c * 2 for c in v[1:]).lower()
        print("    ! een kleur ziet eruit als #ff4d24 — probeer opnieuw")
        uitleg = None


def cmd_merk_nieuw(args):
    """Bouwt vraag voor vraag een merkbestand op.

    Alles kan ook meteen als optie meegegeven worden (--accent, --ink …),
    zodat dit ook zonder gesprek te gebruiken is.
    """
    naam = re.sub(r"[^a-z0-9\-]+", "-", args.naam.lower()).strip("-")
    pad = merkpad(naam)
    if os.path.exists(pad) and not args.overschrijf:
        die(f"{pad} bestaat al (gebruik --overschrijf om hem te vervangen)")

    interactief = sys.stdin.isatty() and not args.stil
    if interactief:
        print(f"\nEen merk maken: {naam}")
        print("  Enter houdt telkens de waarde tussen [haakjes].\n")

    def v(waarde, tekst, standaard, uitleg=None, kleur=False):
        if waarde is not None:
            return waarde
        if not interactief:
            return standaard
        return lees_kleur(tekst, standaard, uitleg) if kleur else vraag(tekst, standaard, uitleg)

    titel = v(args.titel, "Hoe heet je merk", naam.replace("-", " ").title())
    site = v(args.site, "Website (mag leeg)", "")
    wordmark = v(args.wordmark, "Wordmark in beeld", titel.upper(),
                 "Dit staat linksboven in de intro.")
    accent_deel = v(args.wordmark_accent, "Welk stuk daarvan in de accentkleur (mag leeg)", "",
                    "Bij ASKLIEN.ai is dat bijvoorbeeld LIEN.")
    accent = v(args.accent, "Accentkleur", "#2f6df6",
               "Je opvallendste kleur: knoppen, randen, het accentwoord.", kleur=True)
    creme = v(args.achtergrond, "Achtergrondkleur", "#f7f5f2",
              "De rustige kleur van je titelkaart. Meestal bijna wit.", kleur=True)
    ink = v(args.ink, "Tekstkleur", "#1f2328",
            "Je donkerste kleur: koppen, knoppen en de outro.", kleur=True)

    font_keuze = args.font
    if font_keuze is None and interactief:
        print("\n  Lettertype:")
        print("    1. systeemlettertypes — werkt meteen op elke computer")
        print("    2. een eigen lettertype — zet het .ttf eerst in fonts/")
        font_keuze = vraag("Keuze", "1")
    eigen_font = ""
    if str(font_keuze).strip() in ("2", "eigen") or (font_keuze and str(font_keuze) not in ("1", "systeem")):
        eigen_font = args.font if (args.font and str(args.font) not in ("1", "2")) else ""
        if not eigen_font and interactief:
            eigen_font = vraag("Volledige naam van je lettertype", "",
                               "Zoals het in fonts/ staat, bv. 'Archivo Black'.")

    def keten(basis, eigen):
        return f"{eigen} | {basis}" if eigen else basis

    tekst = MERK_SJABLOON.format(
        naam=naam, site=site or '""', wordmark=wordmark,
        accent_deel=accent_deel or '""',
        creme=creme, ink=ink, accent=accent,
        font_zwaar=keten(_ZWAAR, eigen_font),
        font_midden=keten(_MIDDEN, eigen_font),
        font_gewoon=keten(_GEWOON, eigen_font),
        band_tekst=f'"{titel}"' if titel else '""',
        outro_band_tekst='""')
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w", encoding="utf-8") as fh:
        fh.write(tekst)
    print(f"\n✓ {pad} aangemaakt")

    m = laad_merk(naam)
    print("  Afgeleide kleuren: "
          + ", ".join(f"{k} {m[k]}" for k in ("grijs", "muted", "lijn", "perzik")))
    ontbreekt = [s for s in ("font_titel", "font_label", "font_tekst")
                 if not haal_font(m[s])[2]]
    if ontbreekt:
        print(f"  ! let op: {', '.join(ontbreekt)} vindt geen lettertype op deze computer "
              f"— kijk na met ./reelstudio.sh dokter --merk {naam}")

    if args.toon or (interactief and vraag("Nu een voorbeeldbeeld maken? [J/n]", "j").lower().startswith("j")):
        args.merk = naam
        cmd_merk_toon(args)
    else:
        print(f"\n  Bekijk je merk met:   ./reelstudio.sh merk toon {naam}")
        print(f"  Gebruik het in een les met:   merk: {naam}   in storyboard.yaml")


VOORBEELD_STORYBOARD = """titel: Zo ziet jouw huisstijl|eruit in beeld
reeks: Voorbeeld
merk: {merk}
formaat: {formaat}
bron: bron.mp4
intro_punten: [Je kleuren, Je lettertype, Je wordmark]
outro_titel: En dit is je slotbeeld.
outro_punten: [Titelkaart, Ondertitels, Highlights]
outro_volgende: "Klaar om te gebruiken"
webcam: [1338, 824, 404, 228]
intro_duur: 4

stappen:
  - van: 0:00
    titel: Zo ziet een stapkaart eruit

highlights:
  - van: 0:01
    tot: 0:09
    gebied: [660, 380, 600, 320]
    tekst: Zo wijst een highlight

tips:
  - van: 0:01
    tekst: En zo ziet een tipkaart eruit.
    duur: 9
"""

VOORBEELD_SRT = """1
00:00:00,300 --> 00:00:09,000
Zo ziet een ondertitel eruit in jouw huisstijl.
"""


def cmd_merk_lijst(args):
    mapnaam = os.path.join(HERE, "merk")
    namen = sorted(f[:-5] for f in os.listdir(mapnaam) if f.endswith(".yaml"))
    print(f"Merken in {mapnaam}:\n")
    for n in namen:
        m = laad_merk(n)
        ster = " ←  standaard" if n == STANDAARD_MERK else ""
        print(f"  {n:<18} {m.get('naam', n):<16} {hexwaarde(m, 'accent', '?'):<9} {m.get('stijl', '')}{ster}")
    print(f"\n  Bekijken:  ./reelstudio.sh merk toon <naam>")
    print(f"  Nieuw:     ./reelstudio.sh merk nieuw <naam>")


def cmd_merk_toon(args):
    """Rendert één beeld per onderdeel: intro, lichaam en outro.

    Sneller dan een video, en genoeg om te zien of je kleuren en lettertype
    kloppen. Het "scherm" eronder is een neutrale grijze vlakte met een kader,
    zodat je de highlight en de ondertitelpil kunt beoordelen zonder dat er
    een echte opname nodig is.
    """
    naam = args.merk or STANDAARD_MERK
    m = laad_merk(naam)
    lesdir = os.path.join(HERE, ".merkvoorbeeld")
    os.makedirs(lesdir, exist_ok=True)
    bron = os.path.join(lesdir, "bron.mp4")
    if not os.path.exists(bron):
        # een neutraal "scherm": grijze vlakte met een lichter kadertje erin
        r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", f"color=0xd8d8d8:s={W}x{H}:rate={FPS}:duration=10",
                            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                            "-vf", "drawbox=x=640:y=360:w=640:h=360:color=0xf2f2f2:t=fill,"
                                   "drawbox=x=640:y=360:w=640:h=360:color=0xbcbcbc:t=2",
                            "-t", "10", "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", bron])
        if r.returncode != 0:
            die("het voorbeeldbeeld kon niet gemaakt worden — draai ./reelstudio.sh dokter")
    with open(os.path.join(lesdir, "storyboard.yaml"), "w", encoding="utf-8") as fh:
        fh.write(VOORBEELD_STORYBOARD.format(merk=naam, formaat=getattr(args, "formaat", "liggend")))
    with open(os.path.join(lesdir, "ondertitels.srt"), "w", encoding="utf-8") as fh:
        fh.write(VOORBEELD_SRT)

    b = Bouwer(lesdir)
    b.bouw_alles()
    ass_pad = os.path.join(b.uitdir, "voorbeeld.ass")
    b.schrijf_ass(ass_pad)
    for w in b.waarschuwingen:
        print(f"  ! {w}")

    # per moment één stilstaand beeld, met de juiste achtergrond eronder
    ass_esc = ass_pad.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fd_esc = os.path.join(HERE, "fonts").replace(":", "\\:")
    momenten = [
        ("intro", b.intro_d * 0.62, b.kleur(m.get("intro_achtergrond", "creme"))),
        ("lichaam", b.body_start + 3.0, None),   # stapkaart staat er nog
        ("outro", b.body_end + b.outro_d * 0.55, b.kleur(m.get("outro_achtergrond", "ink"))),
    ]
    delen = []
    for label, t, kleur in momenten:
        uit = os.path.join(b.uitdir, f"{label}.png")
        if kleur:
            # het kader van de Bouwer, niet het standaardformaat: anders staat
            # de overlay op 1080x1920 terwijl het beeld eronder 1920x1080 is
            invoer = ["-f", "lavfi", "-i",
                      f"color={'0x' + kleur.lstrip('#')}:s={b.W}x{b.H}:d=0.1"]
        else:
            invoer = ["-ss", "3", "-t", "0.1", "-i", bron]
        # libass tekent wat er op de tijd van het beeld hoort te staan; door de
        # tijdstempel te verschuiven krijgen we het moment dat we willen zien
        vf = f"setpts=PTS+{t:.3f}/TB,"
        if kleur is None:
            # de opname op dezelfde plek leggen als in de echte render
            vf += b.kader.vf(b.kleur(b.kaderkleur())) + ","
        vf += f"ass=filename='{ass_esc}':fontsdir='{fd_esc}'"
        r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + invoer
                           + ["-frames:v", "1", "-vf", vf, uit])
        if r.returncode == 0 and os.path.exists(uit):
            delen.append(uit)
        else:
            print(f"  ! het beeld voor '{label}' kon niet gemaakt worden")
    if not delen:
        die("het voorbeeldbeeld kon niet gerenderd worden")
    fmt = getattr(args, "formaat", "liggend")
    uit_pad = os.path.join(HERE, "merk", f"{naam}-voorbeeld{'' if fmt == 'liggend' else '-' + fmt}.png")
    invoer = []
    for d in delen:
        invoer += ["-i", d]
    richting = "hstack" if b.H > b.W else "vstack"
    breed = 900 if richting == "vstack" else 360 * len(delen)
    filt = ("".join(f"[{i}]" for i in range(len(delen)))
            + f"{richting}=inputs={len(delen)},scale={breed}:-2")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + invoer
                   + ["-filter_complex", filt, uit_pad], check=False)
    print(f"\n✓ voorbeeld: {uit_pad}")
    print("  Open dit beeld en kijk na: kloppen je kleuren, je wordmark en je lettertype?")
    print(f"  Iets aanpassen? Bewerk merk/{naam}.yaml en draai dit opnieuw.")


def cmd_proef(args):
    """Rendert een korte testvideo zonder dat je zelf een opname nodig hebt.

    Dokter zegt of de onderdelen aanwezig zijn; dit zegt of ze samenwerken.
    Alles wat de tool kan tekenen zit erin — intro, ondertitels, stapkaart,
    highlight, tip, prompt, versnelling en outro — dus als dit klopt, klopt
    je installatie.
    """
    lesdir = os.path.join(HERE, "lessen", "proef")
    os.makedirs(lesdir, exist_ok=True)
    bron = os.path.join(lesdir, "bron.mp4")
    if not os.path.exists(bron) or args.opnieuw:
        print("→ testbeeld maken (20 s) …")
        r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration=20",
                            "-f", "lavfi", "-i", "sine=frequency=300:duration=20",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", bron])
        if r.returncode != 0:
            die("het testbeeld kon niet gemaakt worden — draai eerst ./reelstudio.sh dokter")
    merk = args.merk or STANDAARD_MERK
    with open(os.path.join(lesdir, "storyboard.yaml"), "w", encoding="utf-8") as fh:
        fh.write(PROEF_STORYBOARD.format(merk=merk, formaat=args.formaat))
    with open(os.path.join(lesdir, "ondertitels.srt"), "w", encoding="utf-8") as fh:
        fh.write(PROEF_SRT)
    args.les, args.preview, args.van, args.tot = lesdir, True, None, None
    args.zonder_intro, args.uit, args.alleen_ass = False, None, False
    cmd_render(args)
    print("\n✓ de proef is gerenderd. Open de video hierboven en kijk na of je dit ziet:\n"
          "  een titelkaart met je merknaam, ondertitels in een donkere pil, een stapkaart\n"
          "  linksboven, een gekleurd kader rond een stuk beeld, een tip- en promptkaart\n"
          "  rechtsboven, en een outro met een genummerde lijst.\n"
          "  Klopt dat? Dan kun je aan je eigen opname beginnen:\n"
          '      ./reelstudio.sh nieuw mijn-les ~/pad/naar/opname.mp4 --titel "Mijn eerste les"')


def cmd_reel(args):
    """Maakt een reel van een fragment uit een bestaande les.

    De reel verwijst naar dezelfde opname en hetzelfde fragment in de tijd —
    er wordt niets gekopieerd of opnieuw gecodeerd. Ondertitels, highlights,
    tips en stappen die in dat fragment vallen worden overgenomen met hun
    oorspronkelijke tijden, want die staan in broncoördinaten en blijven dus
    kloppen. Je hoeft er alleen nog een hook boven te zetten.
    """
    lesdir = os.path.abspath(args.les)
    sbp = os.path.join(lesdir, "storyboard.yaml")
    if not os.path.exists(sbp):
        die(f"geen storyboard.yaml in {lesdir}")
    sb = yload(sbp) or {}
    bouwer = Bouwer(lesdir)
    duur = bouwer.duur
    van = ptime(args.van) if args.van is not None else 0.0
    tot = ptime(args.tot) if args.tot is not None else min(duur, van + 60)
    if tot <= van:
        die(f"leeg fragment: {ftime(van)}–{ftime(tot)}")
    if tot - van > 95:
        print(f"  ! het fragment duurt {ftime(tot-van)} — een reel mag op Instagram tot 90 s")

    lesnaam = os.path.basename(lesdir.rstrip("/\\"))
    naam = re.sub(r"[^a-z0-9\-]+", "-", (args.naam or f"{lesnaam}-reel").lower()).strip("-")
    uitdir = os.path.join(HERE, "lessen", naam)
    if os.path.exists(uitdir) and not args.overschrijf:
        die(f"{uitdir} bestaat al (gebruik --overschrijf)")
    os.makedirs(uitdir, exist_ok=True)

    def binnen(t):
        return t is not None and van - 0.001 <= t <= tot + 0.001

    # ── onderdelen uit het fragment overnemen ──
    stappen = [x for x in (sb.get("stappen") or []) if binnen(ptime(x.get("van")))]
    highlights = [x for x in (sb.get("highlights") or []) if binnen(ptime(x.get("van")))]
    tips = [x for x in (sb.get("tips") or []) if binnen(ptime(x.get("van")))]
    prompts = [x for x in (sb.get("prompts") or []) if binnen(ptime(x.get("van")))]
    def bijknippen(rij, a_sleutel, b_sleutel):
        """Een versnelling of knip die buiten het fragment doorloopt inkorten."""
        uit = []
        for r in rij:
            a, b = ptime(r[a_sleutel]), ptime(r[b_sleutel])
            if a is None or b is None or b <= van or a >= tot:
                continue
            r = dict(r)
            r[a_sleutel], r[b_sleutel] = ftime(max(a, van)), ftime(min(b, tot))
            if ptime(r[b_sleutel]) - ptime(r[a_sleutel]) >= 0.5:
                uit.append(r)
        return uit

    knip = bijknippen([k if isinstance(k, dict) else {"van": k[0], "tot": k[1]}
                       for k in (sb.get("knip") or [])], "van", "tot")
    versnel = bijknippen(sb.get("versnel") or [], "van", "tot")
    # een stap die vóór het fragment begint maar er nog loopt, wordt de eerste stap
    lopend = [x for x in (sb.get("stappen") or []) if ptime(x.get("van")) is not None
              and ptime(x.get("van")) < van]
    if lopend and not any(abs(ptime(x.get("van")) - van) < 0.5 for x in stappen):
        eerste = dict(lopend[-1])
        eerste["van"] = ftime(van)
        stappen.insert(0, eerste)

    def blok(sleutel, rijen, velden):
        if not rijen:
            return ""
        uit = f"\n{sleutel}:\n"
        for r in rijen:
            eerste = True
            for k in velden:
                if k not in r:
                    continue
                v = r[k]
                if isinstance(v, (list, tuple)):
                    v = "[" + ", ".join(str(x) for x in v) + "]"
                elif isinstance(v, str) and (":" in v or "," in v) and not re.match(r"^\d+:\d", v):
                    v = f'"{v}"'
                uit += f"  {'- ' if eerste else '  '}{k}: {v}\n"
                eerste = False
        return uit

    titel = args.titel or str(sb.get("titel", lesnaam.replace("-", " ").title()))
    hook = args.hook or titel
    # verwijs naar dezelfde opnames; niets kopiëren
    clipregels = "".join(
        f"  - bestand: {os.path.relpath(c.pad, uitdir)}\n"
        + (f"    van: {ftime(c.van)}\n" if c.van > 0.001 else "")
        + (f"    tot: {ftime(c.tot)}\n" if abs(c.tot - c.bestandsduur) > 0.05 else "")
        for c in bouwer.clips)
    tekst = f"""# ══════════════════════════════════════════════════════════════════
#  Reel uit les "{lesnaam}", fragment {ftime(van)}–{ftime(tot)}
#
#  Verwijst naar dezelfde opname — er is niets gekopieerd. Tijden staan in
#  de originele opname, net als in de les zelf, dus de highlights hieronder
#  kloppen zonder omrekenen.
#
#      ./reelstudio.sh render {naam} --preview
# ══════════════════════════════════════════════════════════════════
clips:
{clipregels}formaat: reel
titel: {titel}
merk: {sb.get('merk', STANDAARD_MERK)}
ondertitels: ondertitels.srt
van: {ftime(van)}
tot: {ftime(tot)}

# De eerste seconden beslissen of iemand blijft kijken.
hook: {hook}
hook_duur: 2.6

# Zet intro op nee als je liever meteen in het beeld valt.
intro: {'ja' if args.intro else 'nee'}
outro: ja
outro_titel: {sb.get('outro_titel', 'Zo doe je dat.')}
outro_volgende: "{args.cta}"

# kader: auto     # auto | passen (hele scherm) | vullen (kader vol, rest weg)
"""
    if sb.get("webcam"):
        tekst += f"webcam: [{', '.join(str(v) for v in sb['webcam'])}]\n"
    tekst += blok("stappen", stappen, ("van", "titel", "nummer", "label", "duur"))
    tekst += blok("highlights", highlights, ("van", "tot", "gebied", "tekst", "zoom", "dim", "label"))
    tekst += blok("tips", tips, ("van", "tekst", "duur", "label"))
    tekst += blok("prompts", prompts, ("van", "nummer", "titel", "tekst"))
    tekst += blok("versnel", versnel, ("van", "tot", "factor"))
    if knip:
        tekst += "\nknip:\n" + "".join(f"  - [{k['van']}, {k['tot']}]\n" for k in knip)
    with open(os.path.join(uitdir, "storyboard.yaml"), "w", encoding="utf-8") as fh:
        fh.write(tekst)

    # ── ondertitels van het fragment (met hun oorspronkelijke tijden) ──
    srt_in = os.path.join(lesdir, sb.get("ondertitels", "ondertitels.srt"))
    n_sub = 0
    if os.path.exists(srt_in):
        cues = [c for c in read_srt(srt_in) if c[1] > van and c[0] < tot]
        with open(os.path.join(uitdir, "ondertitels.srt"), "w", encoding="utf-8") as fh:
            for i, (a, b, t) in enumerate(cues, 1):
                fh.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n")
        n_sub = len(cues)
    else:
        print(f"  ! geen ondertitels gevonden in {lesdir} — de reel krijgt er geen")

    print(f"✓ reel klaar in {uitdir}\n"
          f"  fragment {ftime(van)}–{ftime(tot)} ({ftime(tot-van)}) uit {lesnaam}\n"
          f"  overgenomen: {n_sub} ondertitels, {len(stappen)} stappen, {len(highlights)} highlights, "
          f"{len(tips)} tips, {len(prompts)} prompts\n\n"
          f"  1. kijk de hook na in {os.path.join('lessen', naam, 'storyboard.yaml')}\n"
          f"  2. ./reelstudio.sh render {naam} --preview")


def cmd_broll(args):
    """B-roll reels in bulk: per hook één reel met de tekst op het beeld.

    Het formaat dat iedereen kent: mooi beeld, grote tekst, klaar. De hooks
    komen uit een tekstbestand (één per regel); de clips draaien rond als er
    minder clips dan hooks zijn. Elke reel wordt een gewone les-map, dus
    bijsturen kan daarna altijd nog in de studio.
    """
    hooks = [r.strip() for r in open(args.hooks, encoding="utf-8")
             if r.strip() and not r.strip().startswith("#")]
    if not hooks:
        die(f"geen hooks gevonden in {args.hooks} (één per regel)")
    bronnen = [os.path.abspath(b) for b in args.bron]
    for b in bronnen:
        if not os.path.exists(b):
            die(f"bron niet gevonden: {b}")
        if not heeft_beeld(b):
            die(f"{os.path.basename(b)} bevat geen beeld, alleen geluid.")
    stukjes = max(1, int(args.stukjes))
    lengtes = {b: probe_duration(b) for b in bronnen}
    print(f"{len(hooks)} hooks × {len(bronnen)} clip(s), {stukjes} stukje(s) per reel → {len(hooks)} reels\n")
    klaar = []
    for i, hook in enumerate(hooks):
        slug = re.sub(r"[^a-z0-9\-]+", "-", hook.lower()).strip("-")[:40] or f"reel-{i+1}"
        naam = f"broll-{i+1:02d}-{slug}"
        lesdir = os.path.join(HERE, "lessen", naam)
        os.makedirs(lesdir, exist_ok=True)
        # Elke reel pakt een ÁNDER stuk uit de clips: tien hooks op één lange
        # wandelvideo moeten tien verschillende reels opleveren, niet tien keer
        # dezelfde eerste zes seconden. De gulden snede spreidt de beginpunten
        # gelijkmatig zonder toeval — dezelfde invoer geeft dezelfde reels.
        w = (float(args.duur) / stukjes) if args.duur else 0
        gelinkt, rijen = {}, []
        for j in range(stukjes):
            bron = bronnen[(i + j) % len(bronnen)]
            if bron not in gelinkt:
                ext = os.path.splitext(bron)[1].lower() or ".mp4"
                doel = os.path.join(lesdir, f"clip{len(gelinkt)+1}{ext}")
                if not os.path.exists(doel):
                    try:
                        os.symlink(bron, doel)
                    except (OSError, NotImplementedError):
                        shutil.copy2(bron, doel)
                gelinkt[bron] = os.path.basename(doel)
            L = lengtes[bron]
            wj = min(L, w) if w else L
            speling = max(0.0, L - wj)
            frac = ((i * stukjes + j) * 0.618034) % 1.0
            van = frac * speling
            rijen.append(f"  - {{ bestand: {gelinkt[bron]}, van: {ftime(van)}, tot: {ftime(van + wj)} }}")
        r = []
        r.append(f"titel: {hook}")
        r.append("soort: uitleg")
        r.append("formaat: reel")
        r.append(f"merk: {args.merk or STANDAARD_MERK}")
        if args.look:
            r.append(f"look: {args.look}")
        r.append("clips:")
        r += rijen
        r.append(f"hook: {hook}")
        r.append("hook_duur: heel")
        r.append("intro: nee")
        if args.cta:
            r.append("outro: ja")
            r.append(f"outro_volgende: {args.cta}")
        else:
            r.append("outro: nee")
        open(os.path.join(lesdir, "storyboard.yaml"), "w", encoding="utf-8").write("\n".join(r) + "\n")
        print(f"[{i+1}/{len(hooks)}] {hook}")
        rr = subprocess.run([sys.executable, os.path.join(HERE, "reelstudio.py"), "render", naam],
                            capture_output=True, text=True)
        if rr.returncode != 0:
            print(f"  ✗ mislukt:\n{(rr.stderr or rr.stdout).strip()[-400:]}")
            continue
        m = re.search(r"✓ klaar: (\S+)", rr.stdout)
        pad = m.group(1) if m else os.path.join(lesdir, "uit")
        klaar.append(pad)
        print(f"  ✓ {pad}")
    print(f"\n✓ klaar: {len(klaar)} van {len(hooks)} reels")
    if len(klaar) < len(hooks):
        sys.exit(1)


def cmd_transcribeer(args):
    """Maakt alleen de ondertitels — het storyboard blijft onaangeroerd.

    Bestond eerst niet: wie whisper pas installeerde nádat de les al was
    klaargezet, kon alleen `nieuw --overschrijf` draaien, en dat gooit ook
    het storyboard terug naar het sjabloon. Met al je aanwijswerk erin.
    """
    lesdir = os.path.abspath(args.les)
    naam = os.path.basename(lesdir)
    b = Bouwer(lesdir)
    clips = [os.path.basename(c.pad) for c in b.clips]
    audio_bron = b.clips[0].pad if len(clips) == 1 else maak_montage_audio(lesdir, clips)
    model = omgeving.zoek_whisper_model()
    whisper = omgeving.zoek_whisper()
    if not whisper or not model:
        wat = "whisper-cli" if not whisper else f"het model {omgeving.MODEL_NAAM}"
        die(f"{wat} niet gevonden.\n"
            f"  Installeren:  {omgeving.hint('whisper' if not whisper else 'model')}")
    wav = os.path.join(lesdir, ".audio16k.wav")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", audio_bron,
                    "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    print("→ transcriberen met whisper (dit duurt even) …")
    base = os.path.join(lesdir, "transcript_ruw")
    prompt = (args.woordenlijst
              or omgeving.instelling("woordenlijst")
              or "Een tutorial met eigennamen van producten, menu's en knoppen.")
    draai_whisper_met_voortgang([whisper, "-m", model, "-l", args.taal, "-t", "8",
                                 "--prompt", prompt, "-osrt", "-of", base, "-f", wav])
    os.remove(wav)
    rules = load_woordenboek(os.path.join(HERE, "woordenboek.conf"))
    cues = read_srt(base + ".srt")
    subs = os.path.join(lesdir, b.sb.get("ondertitels", "ondertitels.srt"))
    with open(subs, "w", encoding="utf-8") as fh:
        for i, (a, e, tx) in enumerate(cues, 1):
            fh.write(f"{i}\n{srt_time(a)} --> {srt_time(e)}\n{apply_woordenboek(tx, rules)}\n\n")
    print(f"✓ {os.path.basename(subs)} ({len(cues)} regels, woordenboek toegepast) — lees ze na\n"
          f"  in {subs}")


def cmd_studio(args):
    """Start de visuele studio: een pagina op deze computer, geen upload."""
    import studio
    if not omgeving.mogelijkheden(FF)["ass"]:
        print("⚠ " + GEEN_LIBASS.replace("\n  ", "\n  ") + "\n"
              "  De studio gaat open, maar renderen lukt nog niet.\n")
    sys.exit(studio.draai(args.poort, not args.niet_openen))


def cmd_dokter(args):
    """Vertelt wat er op deze computer klaarstaat en wat er nog ontbreekt.

    Dit is het eerste wat iemand draait die de tool net binnengehaald heeft, en
    het eerste wat je vraagt als iemand zegt "het werkt niet". Elke regel die
    fout loopt zegt er meteen bij wat je moet doen.
    """
    from fontmetrics import haal_font, _fontbestanden
    print(f"Reelstudio op {omgeving.SYSTEEM_NAAM}, Python {sys.version.split()[0]}\n")
    problemen, waarschuwingen = [], []

    def regel(ok, wat, uitleg, oplossing=None):
        print(f"  {'✓' if ok else '✗'}  {wat:<24} {uitleg}")
        if not ok and oplossing:
            print(f"     └─ {oplossing}")

    # ── ffmpeg ──
    if FF:
        versie = subprocess.run([FF, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        regel(True, "ffmpeg", versie.replace("ffmpeg version ", "").split(" Copyright")[0] + f"  ({FF})")
        kan = omgeving.mogelijkheden(FF)
        regel(kan["ass"], "libass (overlays)",
              "aanwezig" if kan["ass"] else "ONTBREEKT — zonder libass geen ondertitels of kaarten",
              "./herstel.sh   (probeert vanzelf wat op deze computer werkt)")
        if not kan["ass"]:
            problemen.append("libass")
        encs = kan["encoders"]
        regel(bool(encs), "video-encoders", ", ".join(sorted(encs)) or "geen bruikbare gevonden")
        if encs:
            print(f"     └─ eindrender gebruikt: {' '.join(omgeving.kies_encoder(FF, False)[:2])}"
                  f" · preview: {' '.join(omgeving.kies_encoder(FF, True)[:2])}")
    else:
        regel(False, "ffmpeg", "NIET GEVONDEN — hier stopt alles mee", omgeving.hint("ffmpeg"))
        problemen.append("ffmpeg")

    # ── whisper (optioneel: je kunt ook zelf ondertitels schrijven) ──
    w, model = omgeving.zoek_whisper(), omgeving.zoek_whisper_model()
    regel(bool(w), "whisper-cli", w or "niet gevonden — je kunt ondertitels ook zelf schrijven",
          omgeving.hint("whisper"))
    regel(bool(model), "whisper-model", model or f"{omgeving.MODEL_NAAM} niet gevonden",
          omgeving.hint("model"))
    if not w or not model:
        waarschuwingen.append("automatisch transcriberen")

    # ── fonts ──
    print(f"\n  Fonts ({len(_fontbestanden())} bestanden gevonden op deze computer):")
    merknaam = args.merk or STANDAARD_MERK
    if not os.path.exists(merkpad(merknaam)):
        print(f"  ✗  merkbestand {merkpad(merknaam)} bestaat niet")
        problemen.append("merk")
    else:
        merk = laad_merk(merknaam)
        for rol, sleutel in (("titel", "font_titel"), ("kop", "font_kop"), ("label", "font_label"),
                             ("tekst", "font_tekst"), ("ondertitel", "font_ondertitel")):
            keten = merk.get(sleutel) or merk.get("font_kop") or STANDAARD_FONTS[rol]
            naam, f, gevonden = haal_font(keten)
            if gevonden:
                print(f"  ✓  {sleutel:<18} {naam}")
            else:
                print(f"  ✗  {sleutel:<18} niets uit '{keten}' staat op deze computer")
                print("     └─ zet een .ttf in fonts/, of kies in het merkbestand een font dat je wél hebt")
                problemen.append(sleutel)

    # ── slotsom ──
    print()
    if problemen:
        print(f"✗ {len(problemen)} probleem(en) op te lossen voor je kunt renderen: {', '.join(problemen)}")
        sys.exit(1)
    if waarschuwingen:
        print(f"✓ klaar om te renderen — enkel {', '.join(waarschuwingen)} werkt nog niet")
    else:
        print("✓ alles staat klaar")


def srt_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def detecteer_stiltes(bron, min_duur=5.0, drempel=-38):
    r = subprocess.run([FF, "-hide_banner", "-i", bron, "-af", f"silencedetect=noise={drempel}dB:d={min_duur}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    out = []
    for a, b in zip(starts, ends):
        if out and a - out[-1][1] < 0.5:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def main():
    ap = argparse.ArgumentParser(prog="reelstudio", description="Schermopname → afgewerkte tutorial.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("nieuw", help="maak een lesmap: kopieer bron, transcribeer, maak storyboard")
    p.add_argument("naam")
    p.add_argument("bron", nargs="+", help="een of meer opnames, in de volgorde die je wil")
    p.add_argument("--titel"); p.add_argument("--taal", default="nl")
    p.add_argument("--woordenlijst", help="hint voor whisper (eigen namen, producten)")
    p.add_argument("--stilte", default="5", help="minimale stilte (s) om te versnellen")
    p.add_argument("--link", action="store_true", help="symlink i.p.v. kopie van de bron")
    p.add_argument("--overschrijf", action="store_true")
    p.set_defaults(fn=cmd_nieuw)

    p = sub.add_parser("broll", help="in bulk: per hook één reel met de tekst op b-roll beeld")
    p.add_argument("hooks", help="tekstbestand met hooks, één per regel")
    p.add_argument("bron", nargs="+", help="een of meer b-roll clips (draaien rond)")
    p.add_argument("--duur", type=float, default=8, help="maximale lengte per reel in seconden (0 = hele clip)")
    p.add_argument("--stukjes", type=int, default=1, help="snippets per reel: 2 of 3 maakt er een mini-montage van")
    p.add_argument("--look", help="bv. warm (zie Uiterlijk in de studio)")
    p.add_argument("--merk", help="welk merk (standaard: het standaardmerk)")
    p.add_argument("--cta", help="eindkaart met deze knop erbij (zonder: geen eindkaart)")
    p.set_defaults(fn=cmd_broll)

    p = sub.add_parser("transcribeer", help="maak (alleen) de ondertitels, storyboard blijft staan")
    p.add_argument("les"); p.add_argument("--taal", default="nl")
    p.add_argument("--woordenlijst", help="hint voor whisper (eigen namen, producten)")
    p.set_defaults(fn=cmd_transcribeer)

    p = sub.add_parser("render", help="render de les")
    p.add_argument("les"); p.add_argument("--preview", action="store_true", help="snel, 720p, zonder x264")
    p.add_argument("--van"); p.add_argument("--tot", help="alleen dit stuk (brontijd), zonder intro/outro")
    p.add_argument("--zonder-intro", action="store_true")
    p.add_argument("--uit"); p.add_argument("--alleen-ass", action="store_true")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("check", help="controleer storyboard en toon de tijdlijn")
    p.add_argument("les"); p.set_defaults(fn=cmd_check)

    p = sub.add_parser("merk", help="je eigen huisstijl maken en bekijken")
    msub = p.add_subparsers(dest="merkcmd", required=True)

    q = msub.add_parser("nieuw", help="maak een merkbestand, vraag voor vraag")
    q.add_argument("naam")
    q.add_argument("--titel", help="hoe je merk heet")
    q.add_argument("--site"); q.add_argument("--wordmark")
    q.add_argument("--wordmark-accent", dest="wordmark_accent",
                   help="welk stuk van het wordmark de accentkleur krijgt")
    q.add_argument("--accent", help="accentkleur, bv. #ff4d24")
    q.add_argument("--achtergrond", help="achtergrondkleur van de intro")
    q.add_argument("--ink", help="tekstkleur / donkere kleur")
    q.add_argument("--font", help="volledige naam van je eigen lettertype")
    q.add_argument("--toon", action="store_true", help="meteen een voorbeeldbeeld maken")
    q.add_argument("--formaat", default="liggend", choices=sorted(FORMATEN),
                   help="in welk formaat het voorbeeldbeeld komt")
    q.add_argument("--stil", action="store_true", help="niets vragen, standaardwaarden gebruiken")
    q.add_argument("--overschrijf", action="store_true")
    q.set_defaults(fn=cmd_merk_nieuw)

    q = msub.add_parser("toon", help="render een voorbeeldbeeld van een merk")
    q.add_argument("merk", nargs="?", help="welk merk (standaard: het standaardmerk)")
    q.add_argument("--formaat", default="liggend", choices=sorted(FORMATEN),
                   help="in welk uitvoerformaat")
    q.set_defaults(fn=cmd_merk_toon)

    q = msub.add_parser("lijst", help="welke merken heb je")
    q.set_defaults(fn=cmd_merk_lijst)

    p = sub.add_parser("studio", help="open de visuele studio in je browser")
    p.add_argument("--poort", type=int, default=8765)
    p.add_argument("--niet-openen", dest="niet_openen", action="store_true",
                   help="de browser niet vanzelf openen")
    p.set_defaults(fn=cmd_studio)

    p = sub.add_parser("reel", help="maak een staande reel van een fragment uit een les")
    p.add_argument("les")
    p.add_argument("--van", help="begin van het fragment (m:ss)")
    p.add_argument("--tot", help="einde van het fragment (m:ss)")
    p.add_argument("--naam", help="naam van de reel-map (standaard <les>-reel)")
    p.add_argument("--titel", help="titel in beeld")
    p.add_argument("--hook", help="de eerste regel in beeld (standaard: de titel)")
    p.add_argument("--cta", default="Volg voor meer", help="oproep op de eindkaart")
    p.add_argument("--intro", action="store_true", help="ook een titelkaart vooraan")
    p.add_argument("--overschrijf", action="store_true")
    p.set_defaults(fn=cmd_reel)

    p = sub.add_parser("proef", help="render een korte testvideo om je installatie te bewijzen")
    p.add_argument("--merk", help="welk merk gebruiken (standaard: het standaardmerk)")
    p.add_argument("--formaat", default="liggend", choices=sorted(FORMATEN),
                   help="welk uitvoerformaat testen")
    p.add_argument("--opnieuw", action="store_true", help="maak het testbeeld opnieuw")
    p.set_defaults(fn=cmd_proef)

    p = sub.add_parser("dokter", help="controleer of alles klaarstaat op deze computer")
    p.add_argument("--merk", help="welk merkbestand nakijken (standaard: het standaardmerk)")
    p.set_defaults(fn=cmd_dokter)

    p = sub.add_parser("frame", help="bewaar een beeld (optioneel met raster voor coördinaten)")
    p.add_argument("les"); p.add_argument("tijd"); p.add_argument("--raster", action="store_true")
    p.set_defaults(fn=cmd_frame)

    args = ap.parse_args()
    if args.cmd != "dokter":
        # Alleen wie écht overlays tekent heeft libass nodig. `nieuw` kopieert,
        # transcribeert en maakt een contactvel — dat lukt met elke ffmpeg. Het
        # is onnodig wreed om iemand bij stap 1 al tegen te houden voor iets dat
        # pas bij het renderen telt.
        eis_ffmpeg(overlays=args.cmd in TEKENT_OVERLAYS)
    if hasattr(args, "les"):
        if not os.path.isdir(args.les):
            alt = os.path.join(HERE, "lessen", args.les)
            if os.path.isdir(alt):
                args.les = alt
    args.fn(args)


if __name__ == "__main__":
    main()
