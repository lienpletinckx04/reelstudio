# Reelstudio — werkwijze voor Claude

Deze map zet schermopnames om naar afgewerkte tutorials in de huisstijl van de
gebruiker. Lees eerst `LEESMIJ.md` voor de opties. Dit bestand beschrijft hoe jij een
nieuwe les van begin tot eind afwerkt wanneer iemand een opname aanlevert.

**Eerst controleren of de computer klaarstaat:** `./reelstudio.sh dokter`. Ontbreekt
ffmpeg, libass of een lettertype, los dat op vóór je begint te renderen — anders debug
je een halve les lang iets dat een installatieprobleem is. Op Windows heet het commando
`.\reelstudio.ps1`.

**Welk merk?** Kijk met `./reelstudio.sh merk lijst` welke er zijn. Heeft de gebruiker er
nog geen, maak er dan een met `./reelstudio.sh merk nieuw <naam>` (kan volledig met
opties: `--titel --accent --achtergrond --ink --wordmark --stil`) en toon het resultaat
met `./reelstudio.sh merk toon <naam>`.

## Stappenplan voor een nieuwe les

1. **Aanmaken**
   `./reelstudio.sh nieuw <les-naam> <pad/naar/opname.mp4> --titel "<titel>"`
   → kopieert de bron, transcribeert met whisper, past `woordenboek.conf` toe, zoekt
   stiltes (> 5 s) en maakt `lessen/<les>/storyboard.yaml` + `frames/contact.jpg`.

2. **Begrijpen wat er gebeurt**
   - Lees `transcript_ruw.srt` volledig.
   - Bekijk `frames/contact.jpg` (1 beeld per 30 s) en haal extra beelden op met
     `./reelstudio.sh frame <les> m:ss` (met `--raster` voor coördinaten).
   - Bepaal: wat is de les, wat zijn de stappen, waar moet de kijker klikken/plakken,
     welke prompts worden gebruikt, waar zijn de wachtmomenten.

3. **Ondertitels herschrijven** — de grootste kwaliteitswinst.
   Schrijf `lessen/<les>/ondertitels.txt` (`start|einde|tekst`) op basis van de ruwe
   transcriptie en zet om met `python3 srt_van_txt.py lessen/<les>/ondertitels.txt`.
   Regels: de stem en woordkeuze van de spreker behouden (ook streektaal), stopwoorden
   ("eigenlijk", "dus voilà", "gaan gaan") weg, ASR-fouten fixen (Cloud → Claude),
   timing van whisper aanhouden; hallucinaties (herhaalde zinnen in stiltes) schrappen; haperingen mogen
   weg (en eventueel met `knip` uit de video).
   Citaten van prompts tussen aanhalingstekens. Max ±85 tekens per ondertitel; langere
   worden automatisch gesplitst, maar liever zelf knippen op een leesteken.

4. **Storyboard invullen** (`storyboard.yaml`)
   - `stappen`: 5–9 stappen, werkwoord vooraan ("Kies het krachtigste model"). Intro en
     samenvatting krijgen `nummer: 0` en een `label`.
   - `highlights`: overal waar de kijker iets moet doen (knop, invoerveld, menu).
     Coördinaten uit een raster-frame; `gebied` 8–12 px ruimer dan het element.
     Zoom (1.5–1.6) alleen voor kleine elementen. Labels kort en actief ("Plak hier prompt 1").
     Bij invoervelden onderaan: `label: boven`. Houd het gebied uit de ondertitelzone
     (midden-onder, ±606–1314 × 930–1040) waar mogelijk.
   - `tips`: de gouden regels die ze uitspreekt, één zin, max 2 regels op de kaart.
     Niet tegelijk met een `prompt`-kaart (zelfde plek rechtsboven).
   - `prompts`: telkens als ze een voorbereide prompt plakt → "Prompt n · titel";
     de volledige prompttekst komt in `prompts.md` (lees ze uit de beelden: zoom in op
     het chatvenster met `frame`, de tekst staat letterlijk op het scherm).
   - `versnel`: de voorgestelde stiltes nakijken tegen de ondertitels (geen spraak
     binnen het venster!), marge 0.7 s. `knip` voor haperingen/versprekingen.
   - `intro_punten` = de 3–4 stappen in 1–2 woorden; `outro_titel/punten/volgende`.
   - `webcam`: de zone van het webcam-bubbeltje (meestal rechtsonder; de standaardwaarde
     klopt voor een Loom-opname op 1920×1080). Lees ze anders af uit een raster-frame.

5. **Controleren & previewen**
   `./reelstudio.sh check <les>` (let op `!`-meldingen), daarna stukjes renderen met
   `--van/--tot --preview` en frames bekijken (ffmpeg -ss … -frames:v 1). Kijk na:
   ring rond het juiste element, label leesbaar, geen overlap met ondertitels, zoom
   niet te hard, kaart-teksten niet afgebroken.

6. **Definitief renderen**
   `./reelstudio.sh render <les>` → `lessen/<les>/uit/<les>.mp4` (x264 crf 19).
   Duurt ± de helft van de videoduur. Controleer duur en bestandsgrootte.

7. **Les-materiaal** naast de video:
   - `prompts.md` — alle gebruikte prompts letterlijk (copy-paste-klaar voor onder de les)
   - `les-notities.md` — hoofdstukken met uitvoer-tijdcodes (`check` print ze),
     de tips, en een korte samenvatting voor de lespagina

## De studio

`./reelstudio.sh studio` start een lokale webserver (`studio.py` + `studio/`) met een
pagina waarin de gebruiker een video kiest, stijl instelt, sleept om highlights te
zetten en rendert. De studio is een schil om de CLI: hij schrijft `storyboard.yaml`
en roept `reelstudio.py` aan als subproces. Voeg dus nooit logica toe die alleen in de
studio bestaat — zet ze in `reelstudio.py` en laat de studio ernaar verwijzen, anders
geeft de terminal een ander resultaat dan de knop.

## Meerdere clips

Een les mag uit meerdere opnames bestaan (`clips:` in het storyboard; `bron:` blijft
werken als er één is). Ze worden achter elkaar geplakt tot één tijdlijn en **alle
tijden in het storyboard tellen op díe tijdlijn**, niet per clip. Vertaal dus nooit
zelf naar "clip 2 op 0:07".

- elke clip heeft zijn eigen `Kader`; gebruik `self.kader_op(t)` (niet `self.kader`)
  waar je storyboard-coördinaten omrekent, anders klopt het bij clip 2 niet meer
- `clip_op(t)` geeft de clip op een tijdlijn-moment, `clip.lokaal(t)` de tijd binnen
  dat bestand — nodig zodra je een beeld uit de bron wil halen
- clips zonder audiospoor krijgen stilte bijgemengd; zonder dat weigert concat
- whisper en de stiltedetectie draaien op `maak_montage_audio()`, het gezamenlijke
  geluid, zodat ondertiteltijden over de hele montage kloppen

## Reels en andere formaten

`formaat: reel` (1080x1920) of `vierkant` in het storyboard; standaard is `liggend`.
Een fragment uit een bestaande les omzetten gaat met `./reelstudio.sh reel <les>
--van 2:10 --tot 2:45 --hook "..."` — dat verwijst naar dezelfde opname en neemt de
ondertitels, stappen, highlights en tips uit dat venster over.

Wat je moet weten voor je een reel-storyboard invult:

- **Coördinaten blijven in de bronruimte** (de opname passend in 1920x1080, wat
  `frame --raster` toont). De klasse `Kader` rekent ze om naar het uitvoerkader.
  Reken dus nooit zelf om, en lees ze gewoon af zoals bij een liggende les.
- **`kader: auto|passen|vullen`** bepaalt hoe de opname in het staande kader ligt.
  Auto vult bij een staande bron en past bij een brede. Bij `vullen` kiest
  `kader_midden` welk punt in beeld blijft — nodig als je iemand in de breedte
  filmt en het gezicht niet gecentreerd staat.
- **`hook`** is één regel over het beeld in de eerste seconden; zet `intro: nee`
  als je meteen in het beeld wil vallen. Houd hem kort genoeg voor twee regels.
- **Ruimte is schaars.** In een staand kader passen een hook, een stapkaart en een
  tipkaart niet tegelijk boven het beeld. De tool stapelt ze en schuift wat niet
  past een paar seconden op, met een melding bij `check`. Plan liever meteen zo
  dat er per moment één ding in beeld staat.
- **Houd de outro kort** (één of twee punten, één CTA) — 3 seconden is de norm.

## Huisstijl

Merkbestanden staan in `merk/`. `standaard.yaml` is neutraal en documenteert elke
instelling; `asklien.yaml` volgt www.asklien.ai (editorial: crème/inkt/oranje, zware
koppen, caps-labels, radius 10/18, marquee-band) en `asklien-zacht.yaml` is de oudere
gradient-look.

Een merkbestand mag onvolledig zijn: uit `creme`, `ink` en `accent` worden `grijs`,
`muted`, `lijn`, `perzik` en `muted_donker` afgeleid, en de rest krijgt de waarden uit
`MERK_STANDAARDWAARDEN` in `reelstudio.py`. Zet dus alleen wat afwijkt.

Moet een merk een bestaande website volgen: lees met de browser de computed styles uit
(body bg/color, h1/h2 font+weight+letter-spacing, knoppen bg/radius, kaart-radius) en
werk het merkbestand bij — de componenten zijn merk-gestuurd. Controleer het resultaat
met `./reelstudio.sh merk toon <naam>` in plaats van een hele video te renderen.

Titels van intro/outro breken gebalanceerd af; `|` forceert een regeleinde.

## Technische valkuilen (al opgelost in de code, niet opnieuw uitvinden)

- libass: kleur en alpha apart (`\1c&HBBGGRR&\1a&HAA&`); tekeningen met `\an7` en
  coördinaten rond de oorsprong; ASS-fontgrootte = winAscent+winDescent — daarom staan
  alle groottes in de code in em-pixels en rekent `Bouwer.fs(font, em_px)` ze om.
- Python 3.9 (het systeem-Python van oudere Macs): geen backslashes in
  f-string-expressies, geen tomllib/yaml/PIL. Alleen de standaardbibliotheek.
- Alles wat van de computer afhangt hoort in `omgeving.py`, niet verspreid in de code:
  waar ffmpeg staat, welke encoder werkt, waar fonts en het whisper-model staan.
  Hardcodeer nooit een pad uit één specifieke installatie.
- Encoders moeten getest worden voor gebruik (`omgeving.werkt_encoder`): `-encoders`
  toont wat meegecompileerd is, niet wat op deze machine draait.
- Lettertypes zijn ketens ("ideaal | ook goed | overal aanwezig"). Geef aan libass altijd
  de naam door die `haal_font()` echt gevonden heeft — een onbekende naam wordt
  stilzwijgend vervangen door een ander lettertype met andere breedtes, waardoor de
  pillen en kaarten niet meer om de tekst passen. Gebruik `self.font_tag(rol)`.
- ffmpeg heeft libass nodig; zoom gaat via `zoompan` met `in/30` als tijd.
- Formaat-afhankelijke maten staan in `FORMATEN`, niet los in de code. Er zijn
  drie schalen en ze doen bewust niet hetzelfde: `s` (vorm, = breedte/1920),
  `ts` (tekst die gelezen moet worden — groter in een reel) en `ks` (kaarten —
  net iets groter, want een kaart die een achtste van het scherm vult duwt de
  rest weg). Gebruik `self.tem()` voor leesbare tekst.
- Inline YAML-mappings `{ van: 1:00, tot: 1:10 }` worden ondersteund; verder enkel
  `sleutel: waarde`, lijsten en `[a, b]`.
