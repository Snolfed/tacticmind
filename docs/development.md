# Development guide

## Working on the interface

The interface code lives in `web/src` (React 19 + TypeScript + Vite). The built version goes to `tacticmind/web/static`
and is committed to the repository, so Node.js is not needed to play (CI uses Node 22).

```bash
python main.py --no-window         # game server at http://127.0.0.1:8517
cd web && npm install
npm run dev                        # http://localhost:5173 — code changes show up immediately
npm run typecheck && npm test      # TypeScript (strict) and vitest tests
npm run build                      # new build into tacticmind/web/static
```

## Tests

`python -m pytest` — 185 tests, including:

| File | What it checks |
|---|---|
| `test_perft.py` | perft from the starting position (1–4: 20, 400, 8 902, 197 281), Kiwipete (1–3: 48, 2 039, 97 862), position 3 (1–4: 14, 191, 2 812, 43 238) and positions 4 and 5 from CPW; FEN round-trip and incremental hash/evaluation consistency |
| `test_search.py` | mates in 1, 2 and 3 (classic positions and ones from the Lichess database, also for Black), faster mate, stalemate/mate at the root, MultiPV, statistics, tree, interruption, minimax = alpha-beta with fewer nodes |
| `test_native.py` | C engine: perft (5 positions), mates in 1–3, stalemate/mate at the root, MultiPV, statistics and mini tree, interruption and live counters, NNUE evaluation symmetry, bundled network, C engine selection, mate on the hundredth ply, impossible en passant capture in a FEN |
| `test_engine_process.py` | engine process: `info` after each depth, interruption by a new request, comparison mode, and it ends by itself when the game is killed the hard way |
| `test_rating.py` | Elo E and ΔR for sample values, K during calibration, the Glicko-2 example from the paper, score S and the time penalty, profile and saving |
| `test_selector.py` | the selector hits the target rating range, an easier puzzle after 3 failures, a bonus after 5 successes, ~30% weak themes, no repeats, variety |
| `test_puzzles.py` | Lichess data (every move legal in our generator and in python-chess), puzzle flow, alternative mate, "good move, but there is a better one", Polish-locale notation, stream of thoughts |
| `test_coach.py` | every opening line legal and explained in both languages, opening names and transpositions, opening book, coach strength grows with Elo up to the full engine (a strong coach plays the best moves, a weak one samples), win chance and accuracy, move-class thresholds, "great" and "brilliant", explanations (hanging piece, missed and allowed mate, forks, coach threats), lesson flow and take-backs, game result and the help penalty, 10-game calibration and a level change every 5, profile saving |
| `test_i18n.py` | every language has the full key set and the same `{…}` fields, plurals (Polish: 1/2–4/5+), number formats, piece letters |
| `test_web.py` | TypeScript interface server: settings (validation and saving), navigation and screen snapshots, solving a puzzle and playing a coach game through actions (with the evaluation bar), promotion and legal moves in the snapshot, page/texts/state over HTTP, SSE stream, rejecting foreign requests (Host, missing header, bad JSON, path traversal), the game window with a stand-in for pywebview (address, icon, full screen, closing) and for a Chromium browser (app window, own profile, a second game gets a spare profile), the message when the window cannot open and the NVIDIA + Wayland explicit sync switch |
| `test_training.py` | puzzle modes: theme training draws only that theme, the review queue (order, clean solve removes, limit, missing puzzles, rebuilt from an old profile), Puzzle Rush gets harder without repeats and keeps the best score; on the puzzle screen: switching asks first, review is unrated, a whole Rush run (solve, 3 strikes, summary, again, back) and the clock running out |
| `test_archive.py` | saved coach games: comments and moves survive JSON (and still follow the language), damaged moves are rejected, the advantage graph, PGN export (result, NAGs, `[%eval]`), only the newest 100 games keep their moves, old profiles load; opening a saved game from the list, jumping on the graph, saving the PGN file |

The TypeScript interface has its own tests (`cd web && npm test`, vitest): FEN, trial moves (castling, en passant,
promotion), transition animations between positions, arrows, the evaluation bar, translations and plurals, and the
synthesized sounds (all finite and audible, the move sound short and dry).

The code is also checked with `ruff` and `mypy` (types on all functions, no `type: ignore`
in the game code):

```bash
pip install -r requirements-dev.txt
ruff check .
mypy tacticmind scripts main.py --disallow-untyped-defs
```

GitHub Actions (`.github/workflows/ci.yml`) runs all of this on every pull request and push to `main`: ruff, mypy and
pytest on Python 3.11 and 3.14 (the C engine is built with the runner's gcc), and for the interface vitest, the build and a
check that the committed `tacticmind/web/static` matches `web/src`.

## Puzzles from the Lichess database

Database: <https://database.lichess.org/lichess_db_puzzle.csv.zst> (license **CC0**). Columns:
`PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags`.

```bash
# download the database (about 300 MB), then:
python scripts/build_puzzles.py lichess_db_puzzle.csv.zst                 # 3000 puzzles → tacticmind/data/puzzles.json
python scripts/build_puzzles.py lichess_db_puzzle.csv.zst --count 50 --out tacticmind/data/starter_puzzles.json
```

The script takes puzzles with `Popularity > 80` and `NbPlays > 500` rated 600–2800, splits them into 100-point buckets,
samples the same number of puzzles from each bucket (reservoir sampling with a fixed seed), preferring rare themes,
and checks that all moves are legal. It reads the `.zst` file with the `compression.zstd` module from Python 3.14
(on older Python just decompress it first: `unzstd`).

The repository contains both files: the **starter set** (50 real puzzles, ratings 649–2784, over 50 themes)
and the **full set** of 3000 puzzles. The game uses the full set, and falls back to the starter set when it is missing.

Note on the Lichess format: `FEN` is the position **before** the opponent's move; the first move in `Moves` is played by the opponent,
and the player plays the side to move after it (the board flips to that side).

## Other scripts

| Script | Purpose |
|---|---|
| `scripts/build_engine.py` | compiles the C engine (library + `tmengine` UCI program); `--portable` skips `-march=native`; `--windows-dll` rebuilds the prebuilt Windows library with MinGW-w64 (`x86_64-w64-mingw32-gcc`, e.g. on Linux) |
| `scripts/benchmark.py` | the minimax / alpha-beta measurements from [algorithms.md](algorithms.md) |
| `scripts/match.py` | engine-vs-engine matches (needs `pip install chess` and, for Stockfish, the Stockfish binary) |
| `scripts/nnue/` | NNUE data generation and trainer, see [scripts/nnue/README.md](../scripts/nnue/README.md) |
| `scripts/trace_pieces.py` | traces the piece drawings into SVG (needs `numpy`, `pillow`, `vtracer`, which are not in `requirements.txt`) |
| `scripts/make_icon.py` | makes `web/public/icon.ico` for the Windows window (needs `pillow`) |

Environment variables: `TACTICMIND_HOME` (where the profile is kept), `TACTICMIND_ENGINE=python` (forces the Python engine),
`TACTICMIND_NET` (another NNUE network file), `CC` (the C compiler), and on Linux `TACTICMIND_WINDOW=webview` and
`TACTICMIND_BROWSER=<name>` (see the README).
