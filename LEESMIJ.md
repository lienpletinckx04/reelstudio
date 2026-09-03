# Reelstudio

Van ruwe schermopname naar afgewerkte tutorial — op je eigen computer, zonder
uploads en zonder credits. Eén renderpass met ffmpeg; alle overlays worden als
vectorvormen getekend (libass), dus scherp op elke resolutie.

Werkt op **macOS, Windows en Linux**, en levert liggende video, staande reels
of vierkant.

Wat de tool aan je opname toevoegt:

| Onderdeel | Wat het doet |
|---|---|
| **Intro & outro** | titelkaart in jouw kleuren met wordmark, accentregel en pillen; outro op een donker vlak met genummerde lijst en knop |
| **Ondertitels** | in een afgeronde pil, max 2 regels, blijven uit de webcam-zone |
| **Stappen** | kaart "STAP 2 VAN 7 · Kies je model" bij het begin, daarna een klein chipje linksboven |
| **Highlights** | spotlight (rest dimt), ademende accentrand, label met wijzertje, optioneel inzoomen |
| **Tips / prompts** | kaart rechtsboven die in schuift ("TIP", "PROMPT 1 · Branding-interview") |
| **Knippen / versnellen** | haperingen eruit, wachttijd ×8 met chipje bovenaan |
| **Montage** | meerdere opnames achter elkaar tot één video, elk met eigen beeldkader |
| **Reels** | dezelfde les ook staand (1080×1920) voor Instagram, met hook en eindkaart |
| **Studio** | een interface in je browser: video kiezen, stijl instellen, slepen om aan te wijzen, renderen |

---

## 1. Installeren

```bash
git clone https://github.com/lienpletinckx04/reelstudio.git
cd reelstudio
```

**macOS / Linux**

```bash
./installeer.sh
```

**Windows** (PowerShell)

```powershell
.\installeer.ps1
```

Het script installeert wat ontbreekt (ffmpeg met libass, whisper), haalt het
transcriptiemodel op en kijkt daarna alles na. Je mag het gerust opnieuw
draaien; wat er al staat blijft staan.

### De studio met één dubbelklik

Liever geen terminal? Dubbelklik in Finder op **`Studio starten.command`** (of
op Windows: **`Studio starten.bat`**) — dat doet hetzelfde als het commando
hieronder.

> **De eerste keer** kan macOS zeggen dat het bestand "niet kan worden
> geopend omdat de ontwikkelaar niet geverifieerd kan worden". Dat hoort zo bij
> een script dat je zelf binnenhaalt, niet bij iets uit de App Store. Klik met
> **rechts** op het bestand → **Open** → nog eens **Open** in het venstertje.
> Dat hoef je maar één keer te doen; daarna werkt gewoon dubbelklikken.

Daarna drie commando's die hetzelfde doen, voor als je liever de terminal gebruikt:

```bash
./reelstudio.sh dokter     # wat staat er klaar, wat ontbreekt en hoe je het installeert
./reelstudio.sh proef      # rendert een testvideo — bewijst dat alles samenwerkt
./reelstudio.sh studio     # opent de visuele studio in je browser
```

Op Windows gebruik je overal `.\reelstudio.ps1` in plaats van `./reelstudio.sh`.

> **Werkt er iets niet?** Draai `./reelstudio.sh dokter`. Elke regel die fout
> loopt zegt erbij wat je moet doen. Zie ook [Problemen](#problemen) onderaan.

### Wat je nodig hebt

| | Waarvoor | Verplicht |
|---|---|---|
| **ffmpeg met libass** | het hele renderproces | ja |
| **Python 3** | de tool zelf (geen extra pakketten nodig) | ja |
| **whisper-cli + model** | automatisch ondertitelen | nee — je kunt ondertitels ook zelf schrijven |

---

## 2. De studio: alles in beeld

Wil je niets typen, dan is dit je startpunt:

```bash
./reelstudio.sh studio
```

Je browser opent op `http://127.0.0.1:8765` met vier stappen:

1. **Video** — blader naar je opname of plak een pad. De studio maakt een
   verwijzing naar je bestand; er wordt niets gekopieerd en niets geüpload.
2. **Stijl** — kies liggend, reel of vierkant, kies je huisstijl, en zet je
   titel, hook en eindkaart. Rechts staat de hele tijd een **voorbeeldbeeld uit
   je eigen opname**, met alles erop, dat meteen meeverandert.
3. **Aanwijzen** — schuif door je video en **sleep een kader** over de knop waar
   het om gaat. Dat wordt een highlight. Met de knoppen eronder zet je een stap,
   een tip of een prompt op het moment waar je staat.
4. **Renderen** — preview of eindrender, met een voortgangsbalk. Als het klaar
   is speelt de video meteen in de pagina.

Alles wat je klikt landt gewoon in `lessen/<naam>/storyboard.yaml`. Je kunt dus
in de studio beginnen en in een editor verder werken, of omgekeerd — het is
hetzelfde bestand. De studio rendert ook met exact dezelfde opdrachten als
hieronder, dus je krijgt nooit een ander resultaat dan de terminal zou geven.

> **Waarom lokaal en niet een website?** Je video moet door ffmpeg, en dat staat
> op jouw computer. Een online pagina zou je opname eerst moeten uploaden. Zo
> blijft alles op je eigen machine, gaat het sneller, en kost het niets.

De rest van deze handleiding beschrijft dezelfde dingen via de terminal. Je hebt
ze niet nodig als je in de studio werkt, maar ze leggen wel uit wat elke knop
doet.

---

## 3. Je eigen huisstijl

De tool begint met een neutraal merk. Je eigen huisstijl maak je zo:

```bash
./reelstudio.sh merk nieuw mijnmerk
```

Je krijgt een paar vragen (naam, wordmark, accentkleur, achtergrond, tekstkleur)
en daarna een merkbestand in `merk/mijnmerk.yaml`. Bekijken zonder dat je een
video hoeft te maken:

```bash
./reelstudio.sh merk toon mijnmerk     # → merk/mijnmerk-voorbeeld.png
./reelstudio.sh merk lijst             # welke merken heb je
```

Dat voorbeeldbeeld toont je intro, een stapkaart, een highlight, een tipkaart,
een ondertitel en je outro — alles in jouw kleuren. Klopt er iets niet? Pas
`merk/mijnmerk.yaml` aan en draai `merk toon` opnieuw.

Gebruik je merk in een les door in `storyboard.yaml` te zetten:

```yaml
merk: mijnmerk
```

### Wat er in een merkbestand staat

Alleen wat jou onderscheidt. Drie kleuren volstaan:

```yaml
naam: mijnmerk
wordmark: MIJNMERK
wordmark_accent: MERK        # dit stuk in de accentkleur
creme: "#f7f5f2"             # achtergrond van de intro
ink: "#1f2328"               # koppen, knoppen, de donkere outro
accent: "#2f6df6"            # accentwoord, randen, knoppen
```

Grijstinten, lijntjes en gedempte tekst worden hieruit afgeleid. Alle andere
instellingen (radius, kaartkleuren, ondertitelgrootte, duur van intro en outro)
hebben standaardwaarden die je alleen hoeft te zetten als je ze wilt veranderen —
kijk in `merk/standaard.yaml` voor de volledige lijst met uitleg.

### Lettertypes

Een lettertype geef je op als **keten**:

```yaml
font_kop: Archivo Black | Helvetica Neue Bold | Arial Bold | DejaVu Sans Bold
```

Het eerste lettertype dat op de computer staat wordt gebruikt. Zo ziet je
tutorial er overal goed uit, ook op een computer die jouw lettertype niet heeft.

Wil je een specifiek lettertype? Zet het `.ttf`-bestand in `fonts/` en schrijf
zijn volledige naam vooraan de keten. Controleer met
`./reelstudio.sh dokter --merk mijnmerk` welk lettertype er echt gekozen wordt.

> Dit is geen detail: libass vervangt een onbekende lettertypenaam stilzwijgend
> door een ander lettertype, met andere letterbreedtes. De vlakken die de tool
> rond je tekst tekent kloppen dan niet meer. `dokter` waarschuwt daarvoor.

---

## 4. Een les maken

```bash
# 1. nieuwe les: kopieert de opname, transcribeert, maakt een storyboard
./reelstudio.sh nieuw les2-website ~/Downloads/opname.mp4 --titel "Je website bouwen"

# 2. lees lessen/les2-website/ondertitels.srt na en vul storyboard.yaml in
#    (coördinaten aflezen: ./reelstudio.sh frame les2-website 1:05 --raster)

# 3. controleer en preview
./reelstudio.sh check  les2-website
./reelstudio.sh render les2-website --preview
./reelstudio.sh render les2-website --van 1:00 --tot 1:30 --preview   # alleen een stukje

# 4. definitief
./reelstudio.sh render les2-website
#    → lessen/les2-website/uit/les2-website.mp4
```

**Sneller:** open Claude Code in deze map en zeg *"maak van ~/Downloads/opname.mp4
een tutorial over …"* — `CLAUDE.md` legt uit hoe het storyboard ingevuld wordt,
inclusief het nalezen van de ondertitels en het kiezen van de highlights.

---

## 5. Meerdere opnames aan elkaar

Je filmt zelden alles in één keer goed. Geef ze allemaal mee en ze worden in
die volgorde aan elkaar gemonteerd tot één doorlopende video:

```bash
./reelstudio.sh nieuw mijn-reel opname1.mov opname2.mov opname3.mov
```

Of in de studio: klik in stap 1 gewoon meerdere opnames aan. Met de pijltjes
zet je ze in de juiste volgorde, met het kruisje haal je er een weg.

In het storyboard staat dat zo:

```yaml
clips:
  - bestand: clip1.mp4
    van: 0:03          # optioneel: alleen dit stuk gebruiken
    tot: 0:41
  - bestand: clip2.mp4
  - bestand: clip3.mp4
    tot: 1:12
```

**Alle tijden in de rest van het storyboard tellen op de gemonteerde tijdlijn.**
Staat clip 1 (na knippen) op 38 seconden, dan begint clip 2 op 0:38 — en een
highlight op 0:45 hoort dus bij clip 2. Je rekent nooit met "clip 2 op 0:07":
je kijkt gewoon naar de video zoals hij wordt. `check` drukt de montage af met
de begin- en eindtijd van elke clip, zodat je meteen ziet waar je zit.

Wat er vanzelf goed gaat:

* **Elke clip krijgt zijn eigen kader.** Een staande telefoonopname vult het
  beeld, een breed scherm wordt een strook met merkbalken — ook als ze in
  dezelfde video na elkaar komen.
* **Clips zonder geluid** (een schermopname zonder microfoon) krijgen stilte in
  de plaats, zodat het geluid netjes doorloopt. `check` meldt welke clips dat zijn.
* **Ondertitels en stiltedetectie** luisteren naar alle clips samen, dus de
  tijden kloppen over de hele montage.
* **Verschillende resoluties** door elkaar zijn geen probleem; alles wordt in
  één renderpass naar hetzelfde uitvoerformaat gebracht.

In de studio zie je onder het beeld een strook met je clips. Die laat zien uit
welke opname het huidige beeld komt; klik erop om er meteen heen te springen.

---

## 6. Het storyboard

Alle tijden zijn in de **originele opname** (ook al wordt er geknipt of
versneld — de tool rekent om). Coördinaten zijn pixels op 1920×1080.

```yaml
titel: Je branding maken met Claude Design
reeks: Les 1
merk: mijnmerk                       # merk/mijnmerk.yaml
intro_punten: [Interview-prompt, Kleuren & fonts, Logo als SVG, Merkgids]
outro_titel: Kleuren, fonts, een stem en een logo dat van jou is.
outro_punten: [3 paletten + fonts, Tone of voice, Logo in SVG]
outro_volgende: "Volgende les: je website bouwen"
webcam: [1338, 824, 404, 228]        # x y breedte hoogte van het webcam-bubbeltje

stappen:
  - van: 0:00
    titel: Wat we vandaag maken
    nummer: 0                        # 0 = niet meetellen (intro/samenvatting)
    label: Intro
  - van: 1:03
    titel: Kies het krachtigste model

highlights:
  - van: 1:03.5
    tot: 1:06.2
    gebied: [1252, 312, 84, 60]      # x y breedte hoogte
    tekst: Modelkeuze
    zoom: 1.6                        # optioneel: inzoomen op het gebied
    dim: 0.25                        # optioneel: ja (standaard) / nee / 0–1
    label: boven                     # optioneel: auto / boven / onder

tips:
  - van: 0:42
    tekst: Te snel tevreden = generiek. Blijf prompten.
    duur: 8

prompts:
  - van: 2:30
    nummer: 1
    titel: Branding-interview        # tekst: "De volledige tekst staat onder deze les"

knip:
  - [6:09, 6:16.8]
versnel:
  - { van: 7:20, tot: 7:33, factor: 8 }
```

Tips:

- **Zooms** niet laten overlappen; 1.5–1.6 is genoeg (bron is 1080p).
- **Eén kaart rechtsboven tegelijk** — overlappende tips/prompts worden
  automatisch verschoven (en gemeld bij `check`).
- **Versnellen** alleen waar niets gezegd wordt — `nieuw` stelt stiltes > 5 s al voor.
- **Stappen** zijn tegelijk je hoofdstukken voor onder de video (`check` print ze
  met uitvoertijden).

---

## 7. Reels voor Instagram

Dezelfde tool maakt ook staande video. Zet in het storyboard:

```yaml
formaat: reel        # 1080x1920 · liggend (standaard) | reel | vierkant
```

### Van een les naar een reel

Het snelst is een fragment uit een les die je al hebt:

```bash
./reelstudio.sh reel les2-website --van 2:10 --tot 2:45 --naam modelkeuze \
    --hook "Zo kies je het juiste model"
./reelstudio.sh render modelkeuze --preview
```

Dat maakt `lessen/modelkeuze/` met een storyboard dat naar **dezelfde opname**
verwijst — er wordt niets gekopieerd of opnieuw gecodeerd. De ondertitels,
stappen, highlights en tips die in dat fragment vallen gaan mee, met hun
originele tijden. Eén keer een les uitwerken levert dus gratis reels op.

Een losse korte opname kan ook: maak hem met `nieuw` en zet er
`formaat: reel` in.

### Hoe je opname in het staande kader komt

```yaml
kader: auto          # auto (standaard) | passen | vullen
kader_midden: [960, 400]   # bij vullen: welk punt in beeld moet blijven
```

* **passen** — de hele opname past in beeld, met merkbalken erboven en eronder.
  Een breed scherm wordt dus een strook in het midden, met plaats voor een hook
  bovenaan en ondertitels onderaan.
* **vullen** — de opname vult het kader; wat erbuiten valt gaat weg. Dat wil je
  bij een opname die al staand is, zoals een telefoonvideo van jezelf.
* **auto** kiest zelf: vullen als er nauwelijks iets wegvalt, anders passen. Een
  staande opname vult dus vanzelf, een schermopname wordt vanzelf een strook.

Film je jezelf in de breedte en wil je toch het kader vullen? Zet dan
`kader: vullen` en met `kader_midden` welk punt uit de opname in beeld moet
blijven (coördinaten uit `frame --raster`, zie hieronder).

### De eerste seconde

```yaml
hook: Zo maak je een logo in 30 seconden
hook_duur: 2.6
intro: nee           # geen titelkaart: meteen beeld
```

De hook staat in grote letters óver het beeld, niet op een aparte kaart: een
kaart zonder beweging is precies waar iemand wegscrolt. Bij een brede opname
komt hij in de merkbalk erboven, bij een vullende opname op het beeld met een
vlak eronder zodat hij leesbaar blijft.

De outro is je eindkaart met CTA — houd hem kort:

```yaml
outro_titel: Zo doe je dat.
outro_punten: [Volg voor meer]
outro_volgende: "Link in bio"
```

### Wat er automatisch anders gaat

Je hoeft hier niets voor te doen; het staat er zodat je snapt wat je ziet.

* **Ondertitels worden groter.** Het beeld is kleiner in een reel, maar de tekst
  moet juist groter: hij wordt op een telefoon gelezen, vaak zonder geluid.
* **De onderste 430 en rechterkant 210 pixels blijven vrij.** Daar zet Instagram
  het bijschrift, de gebruikersnaam en de knoppen overheen.
* **Kaarten stapelen in plaats van naast elkaar te staan**, en schuiven een paar
  seconden op als ze elkaar in de weg zitten. `check` meldt dat.
* **De ondertitelpil verdwijnt** als hij op een merkbalk van dezelfde kleur zou
  vallen; de tekst krijgt dan de kleur die wél afsteekt.
* **Coördinaten blijven hetzelfde.** Een `gebied` dat je met `frame --raster`
  hebt afgelezen werkt in beide formaten — de tool rekent zelf om waar dat punt
  in het staande kader terechtkomt. Valt een highlight buiten beeld, dan meldt
  `check` dat.

Je huisstijl in reel-formaat bekijken zonder video:

```bash
./reelstudio.sh merk toon mijnmerk --formaat reel
./reelstudio.sh proef --formaat reel        # volledige testrender
```

### Wat er (nog) niet in zit

Meebewegen met iets in beeld — een camera die een gezicht of een cursor volgt —
zit er niet in. Je kunt wel per highlight inzoomen (`zoom: 1.6`) en met
`kader_midden` één vast punt kiezen. Een bewegend kader met keyframes is de
logische volgende stap.

---

## 8. Ondertitels

`nieuw` transcribeert met whisper (lokaal) en past `woordenboek.conf` toe
("Cloud" → "Claude" …). **Lees ze altijd na** — whisper hoort Nederlands
redelijk, maar niet perfect.

Handig: schrijf of herschrijf in `ondertitels.txt` (`start|einde|tekst` per
regel) en zet om met:

```bash
python3 srt_van_txt.py lessen/<les>/ondertitels.txt
```

Ondertitels die te lang zijn voor twee regels worden automatisch gesplitst op
een leesteken dicht bij het midden.

Geen whisper geïnstalleerd? Dan slaat `nieuw` het transcriberen over en schrijf
je zelf een `ondertitels.srt`. De rest werkt gewoon.

---

## 9. Persoonlijke instellingen

Staat ffmpeg op een rare plek, of heb je het whisper-model al ergens anders?
Kopieer `instellingen_voorbeeld.yaml` naar `instellingen.yaml` en vul in wat je
nodig hebt. Dat bestand blijft buiten git — het bevat paden van jóuw computer.

```yaml
merk: mijnmerk
model: ~/modellen/ggml-large-v3-turbo.bin
woordenlijst: "Les over Claude, Claude Design, prompt, skill."
```

Alles kan ook als omgevingsvariabele, met `TUTORIAL_` ervoor:

```bash
TUTORIAL_MERK=mijnmerk ./reelstudio.sh render mijn-les
```

---

## Bestanden

| Bestand | Doet |
|---|---|
| `Studio starten.command` / `.bat` | dubbelklikken om de studio te openen, zonder terminal |
| `tutorial.sh` / `reelstudio.ps1` / `reelstudio.py` | de hele pijplijn |
| `studio.py` + `studio/` | de visuele studio (lokale webserver + pagina) |
| `omgeving.py` | alles wat van de computer afhangt (ffmpeg, fonts, encoders) |
| `miniyaml.py` | leest het storyboard (geen PyYAML nodig) |
| `fontmetrics.py` | meet tekstbreedtes rechtstreeks uit de fontbestanden |
| `srt_van_txt.py` | `start\|einde\|tekst` → .srt |
| `merk/*.yaml` | kleuren en lettertypes per merk |
| `woordenboek.conf` | vaste correcties op de transcriptie |
| `storyboard_voorbeeld.yaml` | sjabloon voor nieuwe lessen |
| `lessen/<les>/` | bron.mp4, ondertitels, storyboard, `uit/` met de render |

Video's en renders staan bewust niet in git (te groot). Een les meenemen naar
een andere computer is dus: de map `lessen/<les>/` clonen levert het storyboard
en de ondertitels, en de bijhorende `bron.mp4` zet je er zelf naast. Daarna
rendert `render <les>` het eindresultaat identiek opnieuw.

---

## Problemen

**"ffmpeg niet gevonden"** — draai `./installeer.sh`. Op Windows moet je na het
installeren een **nieuw** PowerShell-venster openen; anders kent Windows de
nieuwe map nog niet.

**"deze ffmpeg is gebouwd zonder libass"** — dan kan hij geen overlays tekenen.
Installeer een volledige build (op een Mac: `brew install ffmpeg`, of
`ffmpeg-full` als je die al gebruikte).

**Tekst past niet in de vlakken eromheen** — je lettertype werd niet gevonden en
libass koos zelf iets anders. `./reelstudio.sh dokter --merk <naam>` zegt welk
lettertype er echt gebruikt wordt.

**Titel anders afbreken?** Zet een `|` in de titel:
`titel: Je branding maken|met Claude Design`.

**Kleur of rand verkeerd in een overlay?** Kleuren gaan als `\1c&HBBGGRR&` +
`\1a&HAA&` (apart), nooit als 8-cijferige kleur in `\1c`.

**Vorm staat verschoven?** Teken met `\an7`; `\an5` verschuift tekeningen met
een halve bbox in libass.

**ffmpeg-fout?** De volledige opdracht staat in
`lessen/<les>/uit/laatste_ffmpeg.txt`, de overlay in `uit/<les>.ass` — die kun
je los testen op één beeld:

```bash
ffmpeg -i frames/t65.png -vf ass=uit/les.ass test.png
```


## B-roll reels in bulk

Het bekende formaat: mooi beeld, grote tekst erop, klaar. Zet je hooks in een
tekstbestand (één per regel) en geef één of meer clips mee — per hook komt er
één reel uit, in je huisstijl:

```bash
./reelstudio.sh broll hooks.txt clip1.mp4 clip2.mp4 --merk mijnmerk --cta "Volg voor meer"
```

De clips draaien rond als er minder clips dan hooks zijn, en elke reel pakt een
ánder stuk uit de clips — tien hooks op één lange opname geeft tien verschillende
reels. `--stukjes 2` (of 3) maakt van elke reel een mini-montage van korte
snippets. `--duur 8` bepaalt de maximale lengte per reel; `--look warm` geeft het
beeld de warme grade; zonder `--cta` komt er geen eindkaart. Elke reel wordt een
gewone map onder `lessen/`, dus bijsturen kan daarna in de studio.
