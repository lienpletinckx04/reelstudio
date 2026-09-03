#!/bin/bash
# De tool heet tegenwoordig Reelstudio — dit bestaat zodat oude gewoontes
# (./tutorial.sh studio) en oude instructies gewoon blijven werken.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reelstudio.sh" "$@"
