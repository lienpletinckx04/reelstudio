#!/usr/bin/env python3
"""
yap.py — de rekenkundige kant van praatreels ("yap edits").

Hier staat alles wat een talking-head reel anders maakt dan een tutorial en
dat zonder ffmpeg of libass te kunnen testen: pauzes omzetten naar knippen,
woorden groeperen tot captions, bepalen waar er ingezoomd wordt, en
feedback in gewone taal omzetten naar instellingen.

reelstudio.py doet het tekenen en renderen; dit bestand beslist alleen wát
waar komt. Alleen de standaardbibliotheek (Python 3.9).
"""
import os
import re

# ── pauzes → knippen ────────────────────────────────────────────────
PAUZE_MARGE = 0.12       # zoveel stilte blijft aan elke kant staan, anders klinkt het afgehakt
MIN_KNIP = 0.16          # korter knippen is hoorbaar noch zichtbaar


def pauzes_naar_knips(stiltes, duur, marge=PAUZE_MARGE):
    """[(begin, einde)] stiltes → [(van, tot)] om weg te knippen.

    De stilte aan het begin en einde van de opname verdwijnt helemaal (een
    reel die met adem begint is al weggescrold); tussen de zinnen blijft
    `marge` staan zodat het ritme menselijk blijft.
    """
    knips = []
    for a, b in stiltes:
        van = 0.0 if a <= 0.05 else a + marge
        tot = duur if b >= duur - 0.05 else b - marge
        if tot - van >= MIN_KNIP:
            knips.append((round(van, 3), round(tot, 3)))
    return knips


# ── woorden en captions ──────────────────────────────────────────────
_RUIS = re.compile(r"^[\[\(♪].*[\]\)♪]$")


def lees_woorden(path):
    """Woord-voor-woord SRT (whisper `-ml 1 -sow`) → [(begin, einde, woord)]."""
    with open(path, encoding="utf-8-sig") as fh:
        txt = fh.read().strip().replace("\r", "")
    uit = []
    for blok in re.split(r"\n\s*\n", txt):
        regels = blok.strip().split("\n")
        tijd = next((r for r in regels if "-->" in r), None)
        if not tijd:
            continue
        m = re.findall(r"(\d+):(\d+):(\d+)[,.](\d+)", tijd)
        if len(m) < 2:
            continue
        a, b = [int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0
                for h, mi, s, ms in m[:2]]
        tekst = " ".join(regels[regels.index(tijd) + 1:]).strip()
        if not tekst or _RUIS.match(tekst):
            continue
        # een cue met meerdere woorden eerlijk verdelen naar lengte
        uit.extend(_verdeel(a, b, tekst))
    return uit


def _verdeel(a, b, tekst):
    woorden = tekst.split()
    if len(woorden) == 1:
        return [(a, b, woorden[0])]
    totaal = float(sum(len(w) + 1 for w in woorden))
    t, res = a, []
    for w in woorden:
        d = (b - a) * (len(w) + 1) / totaal
        res.append((t, t + d, w))
        t += d
    return res


def woorden_uit_cues(cues):
    """Terugval als er alleen zinnen zijn: woorden verdelen over de cue."""
    uit = []
    for a, b, tekst in cues:
        uit.extend(_verdeel(a, b, tekst))
    return uit


def woorden_zonder_geknipte(woorden, knips):
    """Woorden die midden in een weggeknipt stuk vallen verdwijnen."""
    def geknipt(w):
        mid = (w[0] + w[1]) / 2
        return any(ka <= mid < kb for ka, kb in knips)
    return [w for w in woorden if not geknipt(w)]


def groepeer_woorden(woorden, max_woorden=3, max_tekens=17, pauze=0.35):
    """Korte stukjes van 1–3 woorden die tegelijk in beeld staan.

    Breekt na een leesteken, na een hoorbare adempauze, of als het stukje
    te breed zou worden voor een telefoon.
    """
    groepen, huidig = [], []
    for w in woorden:
        if huidig:
            gat = w[0] - huidig[-1][1]
            tekens = sum(len(x[2]) + 1 for x in huidig) + len(w[2])
            vorige_eindigt = huidig[-1][2][-1:] in ".?!,;:…"
            if (len(huidig) >= max_woorden or tekens > max_tekens
                    or vorige_eindigt or gat > pauze):
                groepen.append(huidig)
                huidig = []
        huidig.append(w)
    if huidig:
        groepen.append(huidig)
    return groepen


# ── versprekingen en stopwoorden ────────────────────────────────────
VULWOORDEN = {"euh", "euhm", "uh", "uhm", "um", "ehm", "eh", "ehh", "hmm", "mmm"}


def _kaal(w):
    return re.sub(r"[^\w]", "", w.lower())


def vind_versprekingen(woorden, venster_s=5.0):
    """Vulwoorden, dubbele woorden en herstarts → [(van, tot)] om weg te knippen.

    - "euh", "uhm": weg.
    - "ik ik plan": het eerste "ik" weg.
    - herstart: zegt iemand twee woorden en begint dan binnen een paar
      seconden opnieuw met dezelfde twee ("ik plan ... ik plan alles zelf"),
      dan vervalt de mislukte poging tot waar de goede begint.

    Bewust voorzichtig: liever een stuk te weinig knippen dan een zin
    afbreken. Wat het knipt staat in het storyboard en kan je daar terugzetten.
    """
    kaal = [_kaal(w[2]) for w in woorden]
    knips = []
    i = 0
    while i < len(woorden):
        a, b, _ = woorden[i]
        if kaal[i] in VULWOORDEN:
            knips.append((a - 0.02, b + 0.03))
            i += 1
            continue
        if i + 1 < len(woorden) and kaal[i] and kaal[i] == kaal[i + 1] and len(kaal[i]) <= 6:
            knips.append((a - 0.02, woorden[i + 1][0] - 0.03))
            i += 1
            continue
        herstart = None
        if i + 1 < len(woorden) and len(kaal[i]) + len(kaal[i + 1]) >= 5:
            for j in range(i + 2, min(i + 8, len(woorden) - 1)):
                if woorden[j][0] - a > venster_s:
                    break
                if kaal[j] == kaal[i] and kaal[j + 1] == kaal[i + 1]:
                    herstart = j
                    break
        if herstart is not None:
            knips.append((a - 0.02, woorden[herstart][0] - 0.04))
            i = herstart
            continue
        i += 1
    return [(round(max(0.0, x), 3), round(y, 3)) for x, y in knips if y - x >= 0.08]


# ── auto-zoom ───────────────────────────────────────────────────────
ZOOM_NIVEAUS = {
    # (factor, om de hoeveel stukken er ingezoomd wordt)
    "geen":    None,
    "weinig":  (1.08, 3),
    "normaal": (1.12, 2),
    "veel":    (1.18, 1),
}
MIN_ZOOMSTUK = 0.9       # korter dan dit zoomen we niet: het is gewoon gespring
LANG_STUK = 6.0          # een stuk langer dan dit krijgt halverwege een extra zet


def plan_zooms(segmenten, niveau="normaal", midden=(540, 800)):
    """Waar zoomen we in? Elke zin tussen twee sneden is één kans.

    Een snede met een kleine zoomsprong maakt van een montage een bewuste
    montage: de kijker leest het als een nieuw shot en blijft kijken. We
    zoomen daarom op de snede zelf in (vlot) en springen bij de volgende
    snede terug (hard), in plaats van langzaam heen en weer te schuiven.

    segmenten: [(van, tot, snelheid)] in brontijd, zoals Tijdlijn.segs.
    Geeft [(t0, t1, factor, cx, cy, ramp_in)] terug.
    """
    inst = ZOOM_NIVEAUS.get(niveau)
    if not inst:
        return []
    z, elke = inst
    cx, cy = midden
    uit, teller = [], 0
    for a, b, snelheid in segmenten:
        if snelheid != 1.0:
            continue
        d = b - a
        teller += 1
        if d < MIN_ZOOMSTUK:
            continue
        if elke == 1:
            f = z if teller % 2 else round(1 + (z - 1) * 0.5, 3)
        elif (teller % elke) != 0:
            continue
        else:
            f = z
        if d > LANG_STUK:
            uit.append((round(a + d * 0.5, 3), round(b, 3), f, cx, cy, 0.4))
        else:
            uit.append((round(a, 3), round(b, 3), f, cx, cy, 0.14))
    return uit


# ── koppen (headline-stickers) ──────────────────────────────────────
def lees_koppen(lijst, ptime):
    """Storyboard-koppen → [(van, tot, tekst)] in brontijd."""
    uit = []
    for k in lijst or []:
        if not isinstance(k, dict) or not k.get("tekst"):
            continue
        a, b = ptime(k.get("van")), ptime(k.get("tot"))
        if a is None or b is None or b <= a:
            continue
        uit.append((a, b, str(k["tekst"])))
    return uit


# ── geluid ───────────────────────────────────────────────────────────
# Geluidseffecten worden in ffmpeg zelf gemaakt (ruis en een toon met een
# fade): geen bestanden om mee te leveren, geen licentie om over na te denken.
def sfx_bronnen():
    """kind → (lavfi-bron, filterketen). Klinkt als een zachte whoosh / pop."""
    return {
        "whoosh": ("anoisesrc=d=0.5:c=pink:r=48000:a=0.5",
                   "highpass=f=350,lowpass=f=6500,"
                   "afade=t=in:st=0:d=0.2,afade=t=out:st=0.2:d=0.3,volume=0.55"),
        "pop":    ("sine=f=740:d=0.16:r=48000",
                   "afade=t=in:st=0:d=0.01,afade=t=out:st=0.03:d=0.13,volume=0.35"),
    }


# ── feedback in gewone taal → instellingen ───────────────────────────
VOORKEUR_BESTAND = "yap-voorkeuren.yaml"
_ZOOMTRAP = ["geen", "weinig", "normaal", "veel"]


def feedback_naar_wijzigingen(tekst, huidig):
    """Zet "minder zooms" om in {autozoom: weinig}. Geeft (wijzigingen, uitleg).

    Bewust een simpele woordenlijst, geen gokwerk: wat niet herkend wordt komt
    terug als "niet begrepen", zodat je het zelf in het storyboard kan zetten.
    Nederlands én Engels, want zo praten mensen met hun editor.
    """
    t = tekst.lower()
    w, uitleg = {}, []

    def trap(sleutel, richting, lijst):
        nu = str(huidig.get(sleutel, lijst[2] if len(lijst) > 2 else lijst[0]))
        i = lijst.index(nu) if nu in lijst else 2
        return lijst[max(0, min(len(lijst) - 1, i + richting))]

    if re.search(r"(geen|no|zonder|without)\s+(zoom|inzoom)", t):
        w["autozoom"] = "geen"; uitleg.append("geen zooms meer")
    elif re.search(r"(minder|fewer|less|te veel)\s+(zoom|inzoom)", t) or "less zoom" in t:
        w["autozoom"] = trap("autozoom", -1, _ZOOMTRAP); uitleg.append("minder zooms")
    elif re.search(r"(meer|more)\s+(zoom|inzoom)", t):
        w["autozoom"] = trap("autozoom", 1, _ZOOMTRAP); uitleg.append("meer zooms")

    if re.search(r"(geen|no|zonder|without)\s+(geluid|sound|sfx|effect)", t):
        w["geluid"] = False; uitleg.append("geen geluidseffecten")
    elif re.search(r"(geluid|sound|sfx).*(aan|on)\b", t):
        w["geluid"] = True; uitleg.append("geluidseffecten aan")

    if re.search(r"caption\w*.*(omhoog|hoger|up|higher)|(omhoog|hoger|up|higher).*caption", t):
        w["captions_hoogte"] = round(float(huidig.get("captions_hoogte", 0.64)) - 0.06, 2)
        uitleg.append("captions hoger")
    elif re.search(r"caption\w*.*(omlaag|lager|down|lower)|(omlaag|lager|down|lower).*caption", t):
        w["captions_hoogte"] = round(float(huidig.get("captions_hoogte", 0.64)) + 0.06, 2)
        uitleg.append("captions lager")
    if re.search(r"(een|1|één|one)\s+woord|one word", t):
        w["captions_woorden"] = 1; uitleg.append("één woord per keer")
    elif re.search(r"meer woorden|more words|twee woorden|2 woorden", t):
        w["captions_woorden"] = 2 if "twee" in t or "2" in t else 3
        uitleg.append("meer woorden tegelijk")
    if re.search(r"(kleinere|smaller|smaller captions|captions kleiner)", t):
        w["captions_grootte"] = round(float(huidig.get("captions_grootte", 1.0)) - 0.12, 2)
        uitleg.append("captions kleiner")
    elif re.search(r"(grotere|bigger|larger|captions groter)", t):
        w["captions_grootte"] = round(float(huidig.get("captions_grootte", 1.0)) + 0.12, 2)
        uitleg.append("captions groter")
    if re.search(r"(hoofdletters|caps|uppercase).*(uit|weg|niet|off|no)|(geen|no)\s+(hoofdletters|caps)", t):
        w["captions_caps"] = False; uitleg.append("captions in gewone letters")
    elif re.search(r"(hoofdletters|all caps|uppercase)", t):
        w["captions_caps"] = True; uitleg.append("captions in hoofdletters")

    return w, uitleg


def lees_voorkeuren(pad):
    d = {}
    if os.path.exists(pad):
        with open(pad, encoding="utf-8") as fh:
            regels = fh.read().split("\n")
        for r in regels:
            r = r.split("#")[0].strip()
            if ":" in r:
                k, v = r.split(":", 1)
                v = v.strip()
                if v.lower() in ("ja", "true"):
                    v = True
                elif v.lower() in ("nee", "false"):
                    v = False
                else:
                    try:
                        v = float(v) if "." in v else int(v)
                    except ValueError:
                        pass
                d[k.strip()] = v
    return d


def schrijf_voorkeuren(pad, d):
    with open(pad, "w", encoding="utf-8") as fh:
        fh.write("# Wat je Reelstudio over jouw smaak geleerd hebt (`./reelstudio.sh bijsturen`).\n"
                 "# Nieuwe praatreels beginnen hiermee; zet een regel weg om hem te vergeten.\n")
        for k, v in sorted(d.items()):
            fh.write(f"{k}: {'ja' if v is True else 'nee' if v is False else v}\n")
