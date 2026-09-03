# Reelstudio

Turn a raw screen recording or camera clip into a finished, branded tutorial video — locally,
no uploads, no credits. One ffmpeg pass; every overlay is drawn as vector shapes
by libass, so it stays sharp at any resolution.

Runs on **macOS, Windows and Linux**, and outputs landscape video, vertical
Instagram reels or square. Needs ffmpeg (with libass) and Python 3; whisper is
optional and only used for automatic subtitles.

```bash
git clone https://github.com/lienpletinckx04/reelstudio.git
cd reelstudio
./installeer.sh          # Windows: .\installeer.ps1
./reelstudio.sh dokter     # what's ready, what's missing, how to install it
./reelstudio.sh proef      # renders a test video to prove it all works
./reelstudio.sh studio     # opens a visual studio in your browser
```

Prefer clicking to typing? After installing, double-click **`Studio starten.command`**
(Windows: **`Studio starten.bat`**) to open the studio — no terminal needed.

**The studio** is the easy way in: pick a video, choose landscape/reel/square
and a brand, drag a box over the button you want to highlight, and render — all
with a live preview built from your own recording. It runs on your machine
(your video never leaves it) and writes the same `storyboard.yaml` the commands
below use.

Make it yours — three colours are enough:

```bash
./reelstudio.sh merk nieuw mijnmerk    # asks a few questions, writes merk/mijnmerk.yaml
./reelstudio.sh merk toon mijnmerk     # renders a preview image of your brand
```

Then build a lesson — pass several recordings and they are edited together into
one continuous video, each with its own framing:

```bash
./reelstudio.sh nieuw les1 ~/Downloads/take1.mov ~/Downloads/take2.mov --titel "Your first lesson"
./reelstudio.sh render les1 --preview
./reelstudio.sh render les1
```

Turn a fragment of that lesson into a vertical reel — same recording, nothing
copied, subtitles and highlights carried over:

```bash
./reelstudio.sh reel les1 --van 2:10 --tot 2:45 --hook "How to pick the right model"
./reelstudio.sh render les1-reel --preview
```

The tool adds an intro and outro card, subtitles in a rounded pill, step cards,
highlight spotlights with labels, tip and prompt cards, and cuts or speeds up
the boring parts — all driven by one `storyboard.yaml` per lesson.

**The full documentation is in Dutch: [LEESMIJ.md](LEESMIJ.md).**
