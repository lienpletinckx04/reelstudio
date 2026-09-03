# ══════════════════════════════════════════════════════════════════
#  reelstudio.ps1 — Reelstudio starten op Windows.
#
#      .\reelstudio.ps1 dokter
#      .\reelstudio.ps1 proef
#      .\reelstudio.ps1 nieuw les2 C:\opnames\les2.mp4 --titel "Je website bouwen"
#      .\reelstudio.ps1 render les2 --preview
#
#  Zie LEESMIJ.md
# ══════════════════════════════════════════════════════════════════
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Host "Python niet gevonden. Draai eerst .\installeer.ps1" -ForegroundColor Red
    exit 1
}
& $py.Source (Join-Path $PSScriptRoot "reelstudio.py") @args
exit $LASTEXITCODE
