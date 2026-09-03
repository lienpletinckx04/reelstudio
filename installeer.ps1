# ══════════════════════════════════════════════════════════════════
#  installeer.ps1 — zet Reelstudio klaar op Windows.
#
#  Openen: klik met rechts op dit bestand → "Uitvoeren met PowerShell",
#  of typ in een PowerShell-venster:
#
#      .\installeer.ps1
#
#  Krijg je "kan niet worden geladen omdat het uitvoeren van scripts
#  is uitgeschakeld"? Draai dan eerst:
#      Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# ══════════════════════════════════════════════════════════════════
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

$ModelNaam = "ggml-large-v3-turbo.bin"
$ModelUrl  = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$ModelNaam"

function Zeg  { param($t) Write-Host "`n$t" -ForegroundColor White }
function Ok   { param($t) Write-Host "  [ok] $t" -ForegroundColor Green }
function Nok  { param($t) Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Info { param($t) Write-Host "       $t" -ForegroundColor DarkGray }

Zeg "Reelstudio installeren op Windows"

# ── 1. Python ─────────────────────────────────────────────────────
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if ($py) {
    Ok "python $(& $py.Source --version 2>&1)"
} else {
    Nok "Python ontbreekt"
    Info "winget install Python.Python.3.12"
    Info "sluit daarna dit venster en open een nieuw PowerShell-venster"
    exit 1
}

# ── 2. ffmpeg (met libass, anders geen overlays) ──────────────────
function Heeft-Libass {
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ff) { return $false }
    $filters = & ffmpeg -hide_banner -filters 2>$null | Out-String
    return $filters -match "\sass\s"
}

if (Heeft-Libass) {
    Ok "ffmpeg met libass"
} else {
    Nok "ffmpeg ontbreekt (of is gebouwd zonder libass)"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "installeren met winget ..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        Info "Windows kent de nieuwe map pas in een NIEUW venster."
        Info "Sluit dit venster, open PowerShell opnieuw en draai .\installeer.ps1 nog eens."
    } else {
        Info "Installeer ffmpeg van https://www.gyan.dev/ffmpeg/builds/ (full build)"
        Info "en zet de map met ffmpeg.exe in je PATH."
    }
    exit 1
}

# ── 3. whisper (optioneel) ────────────────────────────────────────
if (Get-Command whisper-cli -ErrorAction SilentlyContinue) {
    Ok "whisper-cli"
} else {
    Nok "whisper-cli ontbreekt — nodig om automatisch te transcriberen"
    Info "Download een release van https://github.com/ggml-org/whisper.cpp"
    Info "en zet whisper-cli.exe in je PATH."
    Info "Zonder whisper werkt alles behalve automatisch transcriberen —"
    Info "je kunt ondertitels ook zelf in ondertitels.srt schrijven."
}

# ── 4. transcriptiemodel (±1,5 GB) ────────────────────────────────
New-Item -ItemType Directory -Force -Path "models" | Out-Null
if (Test-Path "models\$ModelNaam") {
    Ok "transcriptiemodel staat klaar"
} else {
    Nok "transcriptiemodel ontbreekt (±1,5 GB)"
    $antwoord = Read-Host "    Nu downloaden? [j/N]"
    if ($antwoord -match "^[jJyY]") {
        try {
            # ProgressPreference uit: de voortgangsbalk maakt de download traag
            $oud = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
            Invoke-WebRequest -Uri $ModelUrl -OutFile "models\$ModelNaam"
            $ProgressPreference = $oud
            Ok "model opgehaald"
        } catch {
            Nok "download mislukt: $_"
            Info "later opnieuw: .\installeer.ps1"
        }
    } else {
        Info "later: Invoke-WebRequest -Uri $ModelUrl -OutFile models\$ModelNaam"
    }
}

# ── 5. eigen instellingen ─────────────────────────────────────────
if ((-not (Test-Path "instellingen.yaml")) -and (Test-Path "instellingen_voorbeeld.yaml")) {
    Copy-Item "instellingen_voorbeeld.yaml" "instellingen.yaml"
    Ok "instellingen.yaml aangemaakt (persoonlijk, gaat niet mee in git)"
}

# ── 6. nakijken ───────────────────────────────────────────────────
Zeg "Nakijken"
& $py.Source reelstudio.py dokter
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Zeg "Klaar"
Write-Host @"
  Bewijs dat alles samenwerkt met een testrender:

      .\reelstudio.ps1 proef

  Daarna je eigen opname:

      .\reelstudio.ps1 nieuw mijn-les C:\pad\naar\opname.mp4 --titel "Mijn eerste les"

  En je eigen huisstijl:

      .\reelstudio.ps1 merk nieuw mijnmerk
"@
