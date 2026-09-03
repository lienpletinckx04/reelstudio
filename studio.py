#!/usr/bin/env python3
"""
studio.py — de visuele kant van Reelstudio.

Draait een kleine webserver op je eigen computer en opent een pagina in je
browser. Daar kies je een video, stel je formaat en huisstijl in, sleep je op
het beeld om aan te wijzen waar de kijker moet kijken, en druk je op renderen.

Waarom lokaal en niet online: je video moet door ffmpeg, en dat staat op jóuw
computer. Een gehoste pagina zou je opname eerst moeten uploaden. Zo blijft
alles op je eigen machine en hoef je niets te wachten of te betalen.

De studio bedenkt niets zelf: alles wat je klikt landt in `storyboard.yaml` en
het renderen gebeurt met dezelfde opdrachten als op de opdrachtregel. Je kunt
dus altijd overschakelen naar de terminal, of andersom.

    ./reelstudio.sh studio
"""
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reelstudio as T          # noqa: E402
import omgeving              # noqa: E402

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")


# ═══════════════════════════════════════════════════════════════════
#  Storyboard schrijven
# ═══════════════════════════════════════════════════════════════════
# miniyaml leest alleen; hier schrijven we terug in dezelfde stijl, zodat een
# storyboard dat de studio maakt met de hand verder bewerkt kan worden.
def _waarde(v):
    if isinstance(v, bool):
        return "ja" if v else "nee"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(str(_kaal(x)) for x in v) + "]"
    return _kaal(v)


def _kaal(v):
    if isinstance(v, float) and v == int(v):
        v = int(v)
    s = str(v)
    if s == "":
        return '""'
    # tijden als 1:03 mogen kaal; alles met dubbelpunt verder moet tussen quotes
    if re.fullmatch(r"\d+:\d\d(\.\d+)?", s):
        return s
    if any(c in s for c in ':#"') or s.strip() != s:
        return '"' + s.replace('"', "'") + '"'
    return s


LIJSTEN = {
    "clips": ("bestand", "van", "tot"),
    "stappen": ("van", "titel", "nummer", "label", "duur"),
    "highlights": ("van", "tot", "gebied", "tekst", "zoom", "dim", "label"),
    "tips": ("van", "tekst", "duur", "label"),
    "prompts": ("van", "nummer", "titel", "tekst"),
    "versnel": ("van", "tot", "factor"),
    "knip": ("van", "tot"),
}
KOP = ("formaat", "titel", "reeks", "merk", "bron", "ondertitels", "van", "tot",
       "kader", "kader_midden", "kader_kleur", "hook", "hook_duur",
       "intro", "outro", "intro_punten", "outro_eyebrow", "outro_titel",
       "outro_punten", "outro_volgende", "webcam", "stapchip", "stapkaart_duur")


def schrijf_storyboard(pad, sb):
    """Storyboard wegschrijven in de volgorde die een mens verwacht.

    Alles wat de studio niet kent schrijven we ook terug. Dat is geen luxe:
    zou hij onbekende sleutels weglaten, dan wist elke stijlwijziging stilletjes
    iets uit dat je met de hand had toegevoegd — en bij `clips:` zou de les
    daarmee zelfs zijn opnames kwijtraken.
    """
    gedaan = set()
    uit = ["# Gemaakt met de studio (./reelstudio.sh studio).\n"
           "# Je mag hier gerust met de hand in verder werken.\n\n"]
    for sleutel in KOP:
        gedaan.add(sleutel)
        if sb.get(sleutel) is None or sb.get(sleutel) == "":
            continue
        uit.append(f"{sleutel}: {_waarde(sb[sleutel])}\n")
    for sleutel, velden in LIJSTEN.items():
        gedaan.add(sleutel)
        rijen = sb.get(sleutel) or []
        if not rijen:
            continue
        uit.append(f"\n{sleutel}:\n")
        for r in rijen:
            if not isinstance(r, dict):
                uit.append(f"  - {_waarde(r)}\n")
                continue
            eerste = True
            for k in list(velden) + [k for k in r if k not in velden]:
                if r.get(k) is None or r.get(k) == "":
                    continue
                uit.append(f"  {'- ' if eerste else '  '}{k}: {_waarde(r[k])}\n")
                eerste = False
    gedaan.add("knip")
    knip = sb.get("knip") or []
    if knip:
        uit.append("\nknip:\n")
        for k in knip:
            a, b = (k["van"], k["tot"]) if isinstance(k, dict) else (k[0], k[1])
            uit.append(f"  - [{_kaal(a)}, {_kaal(b)}]\n")
    rest = [k for k in sb if k not in gedaan and sb[k] is not None and sb[k] != ""]
    if rest:
        uit.append("\n# Zelf toegevoegd — de studio laat dit staan.\n")
        for k in rest:
            v = sb[k]
            if isinstance(v, list) and v and isinstance(v[0], dict):
                uit.append(f"{k}:\n")
                for r in v:
                    eerste = True
                    for kk in r:
                        uit.append(f"  {'- ' if eerste else '  '}{kk}: {_waarde(r[kk])}\n")
                        eerste = False
            else:
                uit.append(f"{k}: {_waarde(v)}\n")
    with open(pad, "w", encoding="utf-8") as fh:
        fh.writelines(uit)


# ═══════════════════════════════════════════════════════════════════
#  Achtergrondwerk met voortgang
# ═══════════════════════════════════════════════════════════════════
TAKEN = {}
_slot = threading.Lock()


class Taak:
    """Een lopend commando, met zijn uitvoer en hoe ver het is.

    Transcriberen en renderen duren minuten. De pagina moet ondertussen kunnen
    tonen wat er gebeurt, dus draait het werk in een thread en halen we de
    voortgang op uit de regels die ffmpeg uitspuwt.
    """

    def __init__(self, cmd, totaal=None, label=""):
        self.id = uuid.uuid4().hex[:12]
        self.cmd = cmd
        self.totaal = totaal          # verwachte duur van de uitvoer in seconden
        self.label = label
        self.regels = []
        self.klaar = False
        self.fout = None
        self.deel = 0.0
        self.bestand = None
        TAKEN[self.id] = self
        threading.Thread(target=self._draai, daemon=True).start()

    def _draai(self):
        try:
            p = subprocess.Popen(self.cmd, cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 errors="replace")
            for regel in p.stdout:
                regel = regel.rstrip()
                m = re.search(r"time=(\d+):(\d\d):(\d\d\.\d+)", regel)
                if m and self.totaal:
                    sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    with _slot:
                        self.deel = max(self.deel, min(0.99, sec / max(0.1, self.totaal)))
                    continue          # voortgangsregels van ffmpeg niet bewaren
                if not regel or regel.startswith("frame="):
                    continue
                with _slot:
                    self.regels.append(regel)
                    if len(self.regels) > 400:
                        del self.regels[:100]
                m = re.search(r"✓ klaar: (\S+)", regel)
                if m:
                    self.bestand = m.group(1)
            code = p.wait()
            if code != 0:
                # "gestopt met code 1" zegt niets. De reden staat in de laatste
                # regels die het commando zelf uitprintte — die horen in de
                # foutmelding, want het logboek is niet altijd in beeld.
                with _slot:
                    staart = [r for r in self.regels if r.strip()][-4:]
                self.fout = "\n".join(staart) if staart else f"gestopt met code {code}"
        except Exception as e:
            self.fout = str(e)
        finally:
            self.deel = 1.0
            self.klaar = True

    def stand(self):
        with _slot:
            return {"id": self.id, "klaar": self.klaar, "fout": self.fout,
                    "deel": round(self.deel, 3), "label": self.label,
                    "regels": self.regels[-40:], "bestand": self.bestand}


# ═══════════════════════════════════════════════════════════════════
#  Beelden
# ═══════════════════════════════════════════════════════════════════
def _ffmpeg(args):
    r = subprocess.run([T.FF, "-y", "-hide_banner", "-loglevel", "error"] + args,
                       capture_output=True)
    return r.returncode == 0, r.stderr.decode("utf-8", "replace")


MINIATUUR_MAP = os.path.join(HERE, ".miniaturen")


def miniatuur(pad):
    """Voorbeeldbeeldje + duur van een videobestand, voor de bestandenkiezer.

    Zonder dit is kiezen gokken: "IMG_2345.mov" zegt niemand iets. Eén keer
    ffmpeg per bestand, daarna komt alles uit .miniaturen/ — de naam bevat
    de wijzigingstijd, dus een overschreven bestand krijgt vanzelf een vers
    beeldje en de oude cache-bestanden zijn hooguit wat verloren kilobytes.
    """
    pad = os.path.abspath(os.path.expanduser(pad))
    if not os.path.isfile(pad):
        return None, 0.0
    try:
        stempel = int(os.path.getmtime(pad))
    except OSError:
        stempel = 0
    sleutel = hashlib.sha1(f"{pad}|{stempel}".encode("utf-8")).hexdigest()[:24]
    os.makedirs(MINIATUUR_MAP, exist_ok=True)
    jpg = os.path.join(MINIATUUR_MAP, sleutel + ".jpg")
    duurpad = os.path.join(MINIATUUR_MAP, sleutel + ".duur")
    if not (os.path.isfile(jpg) and os.path.isfile(duurpad)):
        duur = T.probe_duration(pad)
        # niet het allereerste beeld: dat is vaak zwart of een logo
        t = max(0.3, min(duur * 0.15, max(duur - 0.5, 0.0))) if duur else 0.0
        ok, _ = _ffmpeg(["-ss", f"{t:.2f}", "-i", pad, "-frames:v", "1",
                         "-vf", "scale=240:-2", "-q:v", "5", jpg])
        if not ok and t > 0:
            ok, _ = _ffmpeg(["-i", pad, "-frames:v", "1",
                             "-vf", "scale=240:-2", "-q:v", "5", jpg])
        if not ok:
            return None, duur
        with open(duurpad, "w") as fh:
            fh.write(f"{duur:.3f}")
    try:
        with open(duurpad) as fh:
            duur = float(fh.read().strip() or 0)
        with open(jpg, "rb") as fh:
            return fh.read(), duur
    except (OSError, ValueError):
        return None, 0.0


def bronbeeld(lesdir, t, breedte=960):
    """Eén beeld uit de opname, in de bronruimte.

    Precies de ruimte waarin storyboard-coördinaten staan, zodat een rechthoek
    die je op dit beeld sleept meteen een bruikbaar `gebied` is. Bij meerdere
    clips zoeken we eerst op welke clip dit moment valt.
    """
    b = T.Bouwer(lesdir)
    c = b.clip_op(max(0.0, t))
    merk = b.merk
    uit = os.path.join(lesdir, ".studio_frame.jpg")
    ok, fout = _ffmpeg(["-ss", f"{c.lokaal(t):.3f}", "-i", c.pad, "-frames:v", "1",
                        "-vf", T.normaliseer_vf(merk.get("creme", "#f7f5f2"))
                        + f",scale={breedte}:-2",
                        "-q:v", "4", uit])
    if not ok:
        return None, fout
    with open(uit, "rb") as fh:
        return fh.read(), None


def voorbeeldbeeld(lesdir, t, breedte=540):
    """Hoe het eruitziet mét alle overlays, op dit moment in de opname.

    Dit is de echte opbouw — dezelfde klasse die ook de video maakt — maar dan
    één beeld. Zo zie je binnen een seconde of je hook past en of je highlight
    het juiste vak omcirkelt, zonder een render van minuten.
    """
    b = T.Bouwer(lesdir)
    b.bouw_alles()
    ass = os.path.join(b.uitdir, "studio_voorbeeld.ass")
    b.schrijf_ass(ass)
    c = b.clip_op(max(0.0, t))
    uit_t = b.T(max(ptime_of(t), b.tl.lo))      # tijdlijn → tijd in de uitvoer
    ass_esc = ass.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fd = os.path.join(HERE, "fonts").replace(":", "\\:")
    # het kader van de clip die op dit moment loopt, niet dat van de eerste
    vf = (f"setpts=PTS+{uit_t:.3f}/TB,{c.kader.vf(b.kleur(b.kaderkleur()))},"
          f"ass=filename='{ass_esc}':fontsdir='{fd}',scale={breedte}:-2")
    uit = os.path.join(b.uitdir, "studio_voorbeeld.png")
    ok, fout = _ffmpeg(["-ss", f"{c.lokaal(t):.3f}", "-t", "0.1", "-i", c.pad,
                        "-frames:v", "1", "-vf", vf, uit])
    if not ok:
        return None, fout, b
    with open(uit, "rb") as fh:
        return fh.read(), None, b


def ptime_of(t):
    return float(t)


# ═══════════════════════════════════════════════════════════════════
#  Bestanden zoeken
# ═══════════════════════════════════════════════════════════════════
def snelkoppelingen():
    thuis = os.path.expanduser("~")
    uit = []
    for naam, pad in (("Thuis", thuis), ("Bureaublad", os.path.join(thuis, "Desktop")),
                      ("Downloads", os.path.join(thuis, "Downloads")),
                      ("Films", os.path.join(thuis, "Movies")),
                      ("Video's", os.path.join(thuis, "Videos"))):
        if os.path.isdir(pad):
            uit.append({"naam": naam, "pad": pad})
    return uit


def maplijst(pad):
    pad = os.path.abspath(os.path.expanduser(pad or "~"))
    if not os.path.isdir(pad):
        return {"fout": f"{pad} is geen map"}
    mappen, videos = [], []
    try:
        for naam in sorted(os.listdir(pad), key=str.lower):
            if naam.startswith("."):
                continue
            vol = os.path.join(pad, naam)
            if os.path.isdir(vol):
                mappen.append({"naam": naam, "pad": vol})
            elif naam.lower().endswith(VIDEO_EXT):
                try:
                    mb = os.path.getsize(vol) / 1e6
                except OSError:
                    mb = 0
                videos.append({"naam": naam, "pad": vol, "mb": round(mb)})
    except PermissionError:
        return {"fout": f"geen toegang tot {pad}"}
    return {"pad": pad, "ouder": os.path.dirname(pad) if pad != "/" else None,
            "mappen": mappen, "videos": videos}


# ═══════════════════════════════════════════════════════════════════
#  Gegevens voor de pagina
# ═══════════════════════════════════════════════════════════════════
def merkenlijst():
    uit = []
    mapnaam = os.path.join(HERE, "merk")
    for f in sorted(os.listdir(mapnaam)):
        if not f.endswith(".yaml"):
            continue
        naam = f[:-5]
        try:
            m = T.laad_merk(naam)
        except SystemExit:
            continue
        uit.append({"naam": naam, "titel": str(m.get("naam", naam)),
                    "accent": T.hexwaarde(m, "accent", "#2f6df6"),
                    "creme": T.hexwaarde(m, "creme", "#f7f5f2"),
                    "ink": T.hexwaarde(m, "ink", "#1f2328"),
                    "wordmark": str(m.get("wordmark", naam)),
                    "wordmark_accent": str(m.get("wordmark_accent", "") or ""),
                    "wordmark_gedempt": str(m.get("wordmark_gedempt", "") or "")})
    return uit


def lessenlijst():
    uit = []
    mapnaam = os.path.join(HERE, "lessen")
    if not os.path.isdir(mapnaam):
        return uit
    for naam in sorted(os.listdir(mapnaam)):
        sbp = os.path.join(mapnaam, naam, "storyboard.yaml")
        if not os.path.exists(sbp):
            continue
        try:
            sb = T.yload(sbp) or {}
        except Exception:
            continue
        uit.append({"naam": naam, "titel": str(sb.get("titel", naam)),
                    "formaat": str(sb.get("formaat", "liggend")),
                    "merk": str(sb.get("merk", T.STANDAARD_MERK))})
    return uit


def lesgegevens(naam):
    lesdir = os.path.join(HERE, "lessen", naam)
    sbp = os.path.join(lesdir, "storyboard.yaml")
    if not os.path.exists(sbp):
        return {"fout": f"les '{naam}' bestaat niet"}
    sb = T.yload(sbp) or {}
    try:
        b = T.Bouwer(lesdir)
    except SystemExit:
        return {"fout": f"les '{naam}' kon niet gelezen worden — kijk storyboard.yaml na"}
    duur, k = b.duur, b.kader
    sw, sh = b.src_w, b.src_h
    # de bronruimte per clip: een staande opname heeft een andere dan een brede,
    # en een gesleept kader moet naar de júiste ruimte omgerekend worden
    clips = [{"naam": os.path.basename(c.pad), "start": round(c.start, 2),
              "einde": round(c.einde, 2), "breedte": c.src_w, "hoogte": c.src_h,
              "bronruimte": [round(c.kader.bron_w), round(c.kader.bron_h)],
              "modus": c.kader.modus, "geluid": c.audio} for c in b.clips]
    srt = os.path.join(lesdir, sb.get("ondertitels", "ondertitels.srt"))
    n_sub = len(T.read_srt(srt)) if os.path.exists(srt) else 0
    renders = []
    uitdir = os.path.join(lesdir, "uit")
    if os.path.isdir(uitdir):
        for f in sorted(os.listdir(uitdir)):
            if f.endswith(".mp4"):
                renders.append({"naam": f, "mb": round(os.path.getsize(os.path.join(uitdir, f)) / 1e6)})
    return {"naam": naam, "storyboard": sb, "duur": duur,
            "bron_breedte": sw, "bron_hoogte": sh,
            "bronruimte": [round(k.bron_w), round(k.bron_h)],
            "kader_modus": k.modus, "ondertitels": n_sub, "renders": renders,
            "clips": clips, "heeft_bron": True}


# ═══════════════════════════════════════════════════════════════════
#  De server
# ═══════════════════════════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    server_version = "Reelstudio"

    def log_message(self, *_a):
        pass                      # geen ruis in de terminal

    # ── hulpjes ───────────────────────────────────────────────────
    def stuur(self, data, type_="application/json", code=200):
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def fout(self, bericht, code=400):
        self.stuur({"fout": bericht}, code=code)

    def lees_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ── GET ───────────────────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = unquote(u.path)
        try:
            self._get(p, q)
        except SystemExit:
            # reelstudio.py stopt met die() bij een fout in het storyboard; in de
            # server mag dat de verbinding niet verbreken
            self.fout("het storyboard kon niet gelezen worden — kijk het na", 500)
        except Exception as e:
            self.fout(f"{type(e).__name__}: {e}", 500)

    def _get(self, p, q):
        if p == "/":
            return self.bestand(os.path.join(HERE, "studio", "index.html"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            naam = os.path.basename(p)
            vol = os.path.join(HERE, "studio", naam)
            if not os.path.exists(vol):
                return self.fout("niet gevonden", 404)
            type_ = mimetypes.guess_type(vol)[0] or "application/octet-stream"
            return self.bestand(vol, type_ + ("; charset=utf-8" if "text" in type_ or "javascript" in type_ else ""))

        if p == "/favicon.ico":
            # een klein blauw vierkantje, zodat de browser niet naar een 404 zoekt
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                   '<rect width="32" height="32" rx="7" fill="#2f6df6"/>'
                   '<rect x="9" y="12" width="14" height="8" rx="2" fill="#fff"/></svg>')
            return self.stuur(svg, "image/svg+xml")
        if p == "/api/start":
            ff_ok = bool(T.FF) and omgeving.mogelijkheden(T.FF)["ass"] if T.FF else False
            return self.stuur({
                "formaten": [{"naam": k, "breedte": v["breedte"], "hoogte": v["hoogte"]}
                             for k, v in T.FORMATEN.items()],
                "merken": merkenlijst(), "lessen": lessenlijst(),
                "snelkoppelingen": snelkoppelingen(),
                "standaardmerk": T.STANDAARD_MERK,
                "ffmpeg": ff_ok,
                "whisper": bool(omgeving.zoek_whisper() and omgeving.zoek_whisper_model()),
            })
        if p == "/api/map":
            return self.stuur(maplijst(q.get("pad", "~")))
        if p == "/api/bestand":
            # Een pad dat iemand zelf intikt is niet per se een video. Meteen
            # nakijken, want anders merk je het pas nadat je alles ingevuld hebt.
            pad = os.path.abspath(os.path.expanduser(q.get("pad", "")))
            if not os.path.isfile(pad):
                return self.stuur({"ok": False, "reden": "dat bestand bestaat niet"})
            if not T.heeft_beeld(pad):
                return self.stuur({"ok": False, "reden":
                    os.path.basename(pad) + " bevat geen beeld, alleen geluid "
                    "— een .mp3 is een geluidsbestand, geen video"})
            return self.stuur({"ok": True, "pad": pad})
        if p == "/api/miniatuur":
            beeld, duur = miniatuur(q.get("pad", ""))
            if beeld is None:
                return self.fout("geen beeld uit dit bestand te halen", 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(beeld)))
            self.send_header("X-Duur", f"{duur:.1f}")
            # de cache-sleutel zit in het bestand zelf; de browser mag dit onthouden
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            try:
                self.wfile.write(beeld)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if p.startswith("/api/les/"):
            return self.stuur(lesgegevens(p[len("/api/les/"):]))
        if p.startswith("/api/frame/"):
            naam = p[len("/api/frame/"):]
            data, fout = bronbeeld(os.path.join(HERE, "lessen", naam), float(q.get("t", 0)))
            if data is None:
                return self.fout(fout or "beeld mislukt", 500)
            return self.stuur(data, "image/jpeg")
        if p.startswith("/api/voorbeeld/"):
            naam = p[len("/api/voorbeeld/"):]
            data, fout, b = voorbeeldbeeld(os.path.join(HERE, "lessen", naam), float(q.get("t", 0)))
            if data is None:
                return self.fout(fout or "voorbeeld mislukt", 500)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Waarschuwingen", json.dumps(b.waarschuwingen)[:3000])
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(data)
        if p.startswith("/api/ondertitels/"):
            naam = p[len("/api/ondertitels/"):]
            lesdir = os.path.join(HERE, "lessen", naam)
            sb = T.yload(os.path.join(lesdir, "storyboard.yaml")) or {}
            srt = os.path.join(lesdir, sb.get("ondertitels", "ondertitels.srt"))
            cues = T.read_srt(srt) if os.path.exists(srt) else []
            return self.stuur({"cues": [{"van": round(a, 3), "tot": round(b, 3), "tekst": tx}
                                        for a, b, tx in cues]})
        if p.startswith("/api/taak/"):
            t = TAKEN.get(p[len("/api/taak/"):])
            return self.stuur(t.stand() if t else {"fout": "onbekende taak"})
        if p.startswith("/uit/"):
            deel = p[len("/uit/"):].split("/", 1)
            if len(deel) != 2:
                return self.fout("niet gevonden", 404)
            vol = os.path.join(HERE, "lessen", deel[0], "uit", os.path.basename(deel[1]))
            if not os.path.exists(vol):
                return self.fout("niet gevonden", 404)
            return self.bestand(vol, mimetypes.guess_type(vol)[0] or "video/mp4", stream=True)
        return self.fout("niet gevonden", 404)

    def bestand(self, pad, type_, stream=False):
        """Serveert een bestand, met deelverzoeken (Range) voor video.

        Een <video> vraagt stukken op — om vooruit te spoelen, of gewoon om
        te beginnen spelen voor alles binnen is. Zonder 206-antwoorden kan
        Chromium besluiten dat de bron onbruikbaar is en krijg je een video
        die er wel staat maar niets doet.
        """
        n = os.path.getsize(pad)
        van, tot = 0, n - 1
        bereik = self.headers.get("Range") if stream else None
        m = re.match(r"bytes=(\d*)-(\d*)$", bereik or "")
        deel = bool(m and (m.group(1) or m.group(2)))
        if deel:
            if m.group(1):
                van = int(m.group(1))
                if m.group(2):
                    tot = min(int(m.group(2)), n - 1)
            else:
                # "bytes=-500": de laatste 500 bytes
                van = max(0, n - int(m.group(2)))
            if van >= n:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{n}")
                self.end_headers()
                return
        self.send_response(206 if deel else 200)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(tot - van + 1))
        if stream:
            self.send_header("Accept-Ranges", "bytes")
        if deel:
            self.send_header("Content-Range", f"bytes {van}-{tot}/{n}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(pad, "rb") as fh:
                fh.seek(van)
                over = tot - van + 1
                while over > 0:
                    blok = fh.read(min(1 << 16, over))
                    if not blok:
                        break
                    self.wfile.write(blok)
                    over -= len(blok)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ── POST ──────────────────────────────────────────────────────
    def do_POST(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        body = self.lees_json()
        try:
            self._post(p, body)
        except SystemExit:
            self.fout("het storyboard kon niet gelezen worden — kijk het na", 500)
        except Exception as e:
            self.fout(f"{type(e).__name__}: {e}", 500)

    def _post(self, p, body):
        if p == "/api/les":
            return self.nieuwe_les(body)
        if p.startswith("/api/les/"):
            naam = p[len("/api/les/"):]
            lesdir = os.path.join(HERE, "lessen", naam)
            if not os.path.isdir(lesdir):
                return self.fout(f"les '{naam}' bestaat niet")
            sb = body.get("storyboard") or {}
            schrijf_storyboard(os.path.join(lesdir, "storyboard.yaml"), sb)
            return self.stuur({"ok": True})
        if p.startswith("/api/render/"):
            naam = p[len("/api/render/"):]
            g = lesgegevens(naam)
            if g.get("fout"):
                return self.fout(g["fout"])
            preview = bool(body.get("preview", True))
            cmd = [sys.executable, os.path.join(HERE, "reelstudio.py"), "render", naam]
            if preview:
                cmd.append("--preview")
            fm = T.FORMATEN.get(g["storyboard"].get("formaat", "liggend"), T.FORMATEN["liggend"])
            grof = g["duur"] + fm["intro_duur"] + fm["outro_duur"]
            t = Taak(cmd, totaal=grof, label="preview" if preview else "eindrender")
            return self.stuur({"taak": t.id})
        if p.startswith("/api/ondertitels/"):
            # De tijden komen uit het bestand zelf en blijven staan; alleen de
            # tekst is aan te passen. Zo kan een tikfout van whisper niet
            # uitgroeien tot een verschoven ondertitelspoor.
            naam = p[len("/api/ondertitels/"):]
            lesdir = os.path.join(HERE, "lessen", naam)
            if not os.path.isdir(lesdir):
                return self.fout(f"les '{naam}' bestaat niet")
            sb = T.yload(os.path.join(lesdir, "storyboard.yaml")) or {}
            srt = os.path.join(lesdir, sb.get("ondertitels", "ondertitels.srt"))
            cues = body.get("cues")
            if not isinstance(cues, list):
                return self.fout("geen ondertitels meegekregen")
            with open(srt, "w", encoding="utf-8") as fh:
                n = 0
                for c in cues:
                    tekst = str(c.get("tekst", "")).strip()
                    if not tekst:
                        continue          # leeggemaakt = weggehaald
                    n += 1
                    fh.write(f"{n}\n{T.srt_time(float(c['van']))} --> "
                             f"{T.srt_time(float(c['tot']))}\n{tekst}\n\n")
            return self.stuur({"ok": True, "aantal": n})
        if p == "/api/broll":
            hooks = [str(h).strip() for h in (body.get("hooks") or []) if str(h).strip()]
            bronnen = [os.path.expanduser(str(b)) for b in (body.get("bronnen") or []) if b]
            if not hooks:
                return self.fout("geen hooks — één per regel in het tekstvak")
            if not bronnen:
                return self.fout("kies eerst een of meer clips (bovenaan bij de video's)")
            for b_ in bronnen:
                if not os.path.exists(b_):
                    return self.fout(f"clip niet gevonden: {b_}")
            hb = os.path.join(HERE, "lessen", ".broll_hooks.txt")
            with open(hb, "w", encoding="utf-8") as fh:
                fh.write("\n".join(hooks) + "\n")
            cmd = [sys.executable, os.path.join(HERE, "reelstudio.py"), "broll", hb] + bronnen
            if body.get("merk"):
                cmd += ["--merk", str(body["merk"])]
            if body.get("cta"):
                cmd += ["--cta", str(body["cta"])]
            if body.get("duur"):
                cmd += ["--duur", str(body["duur"])]
            if body.get("stukjes"):
                cmd += ["--stukjes", str(int(body["stukjes"]))]
            if body.get("look"):
                cmd += ["--look", str(body["look"])]
            t_ = Taak(cmd, totaal=None, label=f"{len(hooks)} b-roll reels")
            return self.stuur({"taak": t_.id, "aantal": len(hooks)})
        if p.startswith("/api/transcribeer/"):
            # via het transcribeer-commando: dat raakt alleen de ondertitels
            # aan. (De oude route draaide `nieuw --overschrijf`, en dat gooit
            # ook het storyboard terug naar het sjabloon — met al het
            # aanwijswerk erin.)
            naam = p[len("/api/transcribeer/"):]
            cmd = [sys.executable, os.path.join(HERE, "reelstudio.py"), "transcribeer", naam]
            g = lesgegevens(naam)
            totaal = g.get("duur") if isinstance(g, dict) and not g.get("fout") else None
            t = Taak(cmd, totaal=totaal, label="transcriberen — duurt enkele minuten")
            return self.stuur({"taak": t.id})
        return self.fout("niet gevonden", 404)

    def nieuwe_les(self, body):
        bron = body.get("bron")
        paden = [os.path.expanduser(str(b)) for b in (bron if isinstance(bron, list) else [bron])]
        paden = [p for p in paden if p and p != "None"]
        if not paden:
            return self.fout("geen video gekozen")
        for p_ in paden:
            if not os.path.exists(p_):
                return self.fout(f"video niet gevonden: {p_}")
        naam = re.sub(r"[^a-z0-9\-]+", "-", str(body.get("naam") or
                      os.path.splitext(os.path.basename(paden[0]))[0]).lower()).strip("-") or "les"
        lesdir = os.path.join(HERE, "lessen", naam)
        if os.path.exists(lesdir) and not body.get("overschrijf"):
            return self.fout(f"'{naam}' bestaat al — kies een andere naam", 409)
        cmd = [sys.executable, os.path.join(HERE, "reelstudio.py"), "nieuw", naam] + paden + ["--link"]
        if body.get("titel"):
            cmd += ["--titel", str(body["titel"])]
        if body.get("overschrijf"):
            cmd.append("--overschrijf")
        # de balk loopt op de whisper-tijdstempels; zonder totaal blijft ze
        # op nul staan en lijkt een lange transcriptie kapot
        totaal = sum(T.probe_duration(p_) for p_ in paden) or None
        t = Taak(cmd, totaal=totaal, label="les klaarzetten — ondertitels maken duurt enkele minuten")
        return self.stuur({"taak": t.id, "naam": naam})


def draai(poort=8765, openen=True):
    if not T.FF:
        print("✗ ffmpeg niet gevonden — draai eerst ./reelstudio.sh dokter", file=sys.stderr)
        return 1
    os.makedirs(os.path.join(HERE, "lessen"), exist_ok=True)
    adres = f"http://127.0.0.1:{poort}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", poort), Handler)
    except OSError as e:
        print(f"✗ poort {poort} is al in gebruik ({e}).\n"
              f"  Draait de studio al in een ander venster? Open dan {adres}\n"
              f"  Of kies een andere poort:  ./reelstudio.sh studio --poort {poort + 1}",
              file=sys.stderr)
        return 1
    print(f"\n  Reelstudio draait op {adres}\n"
          f"  Je video's blijven op deze computer.\n"
          f"  Stoppen: Ctrl-C\n")
    if openen:
        threading.Timer(0.6, lambda: webbrowser.open(adres)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  studio gestopt")
    return 0


if __name__ == "__main__":
    poort = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    sys.exit(draai(poort))
