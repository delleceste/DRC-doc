#!/bin/sh
# Build a PDF from one of the markdown documents in this directory.
#
#   ./make-pdf.sh              -> NOTES.pdf        (default)
#   ./make-pdf.sh REW-INVERSION.md -> REW-INVERSION.pdf
#
# Needs pandoc and pdflatex.  There is no xelatex on this machine, so the
# Unicode handling lives in pdf-header.tex -- if you add a new symbol and the
# build fails with "Unicode character ... not set up", add a \newunicodechar
# line there.  Check which glyphs a document uses with:
#   python3 -c "print(sorted({c for c in open('FILE.md').read() if ord(c)>127}))"
set -e
cd "$(dirname "$0")"

SRC=${1:-NOTES.md}
OUT="${SRC%.md}.pdf"

case "$SRC" in
    NOTES.md)         TITLE="Room correction working notes — history and retractions" ;;
    REW-INVERSION.md) TITLE="Room correction by inversion in REW — a step-by-step guide" ;;
    SUBWOOFER-INTEGRATION.md) TITLE="Subwoofer integration under a single-DAC constraint" ;;
    *)                TITLE="${SRC%.md}" ;;
esac

pandoc "$SRC" \
    -o "$OUT" \
    --from=markdown+gfm_auto_identifiers \
    --pdf-engine=pdflatex \
    --include-in-header=pdf-header.tex \
    --toc --toc-depth=3 \
    --metadata title="$TITLE" \
    --metadata author="giacomo" \
    --metadata date="$(date +%Y-%m-%d)" \
    -V geometry:a4paper \
    -V geometry:margin=2cm \
    -V fontsize=10pt \
    -V colorlinks=true \
    -V linkcolor=RoyalBlue \
    -V urlcolor=RoyalBlue \
    -V toccolor=black

echo "wrote $OUT ($(ls -lh "$OUT" | awk '{print $5}'), $(pdfinfo "$OUT" 2>/dev/null | awk '/^Pages/{print $2}') pages)"
