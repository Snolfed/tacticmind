Fonts of the interface (served by the game at /fonts/…):

- Space Grotesk (interface text), Space Mono (numbers, moves, the engine's figures) and Bricolage Grotesque
  (headings, the logo) — SIL Open Font License 1.1, license texts in LICENSE-OFL-fonts.txt. The WOFF2 files come from
  the Fontsource packages (@fontsource-variable/space-grotesk, @fontsource/space-mono,
  @fontsource-variable/bricolage-grotesque 5.3.0), split into the "latin" and "latin-ext" subsets (Polish letters
  are in latin-ext); Space Grotesk and Bricolage Grotesque are variable fonts (weights 300–700 and 200–800).
- Noto fonts (Google): Noto Sans (Regular, Bold) and Noto Sans Mono — the fallback for characters the fonts above do
  not have (Greek, arrows, maths, symbols). Copied from the noto-fonts package; the license text from that package:
  LICENSE-noto-fonts.txt.

The Noto files are subsets in WOFF2 (about 60 KB each instead of 600 KB): Latin with Polish letters, Greek,
punctuation, arrows, maths, box drawing and symbols. Characters outside these ranges fall back to the system font.
Regenerate from the full TTF files with fontTools (pip install fonttools brotli):

  pyftsubset NotoSans-Regular.ttf --layout-features='*' --flavor=woff2 --output-file=NotoSans-Regular.woff2 \
    --unicodes="U+0020-007E,U+00A0-017F,U+0370-03FF,U+2000-206F,U+20A0-20CF,U+2100-214F,U+2190-21FF,U+2200-22FF,U+2500-257F,U+25A0-25FF,U+2600-27BF"
