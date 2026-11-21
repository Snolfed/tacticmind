# TacticMind — chess tactics puzzles and an AI coach that thinks out loud

TacticMind is a chess tactics trainer in the style of chess.com "Puzzles", with a chess engine **written from scratch**
in this project. You solve real puzzles from the Lichess database, and next to the board the **"AI Brain"** panel shows
live what the engine is calculating: depth, node count, alpha-beta cutoffs, the three best moves with their lines, a mini
search tree and a "stream of thoughts" in plain language. A second game mode lets you **play against a coach** whose
strength you choose (400–2900 Elo) and who rates and explains every move you make.

![Coach Maks](tacticmind/assets/coach.png)

No ready-made engine is used in the game. The engine is written in **C** (bitboards, PVS alpha-beta search) and evaluates
positions with an **NNUE neural network trained in this project** on the engine's own games. A simpler version of the
engine in Python is kept as a fallback and for explaining the algorithms. Everything runs locally: no server, no internet
connection and no account are needed to play.

## Contents

1. [Features](#features)
2. [Installation and running on Windows](#installation-and-running-on-windows)
3. [Linux and macOS](#linux-and-macos)
4. [Using the game](#using-the-game)
5. [Troubleshooting](#troubleshooting)
6. [Project structure](#project-structure)
7. [How it works](#how-it-works)
8. [Results](#results)
9. [Tests and code quality](#tests-and-code-quality)
10. [Documentation](#documentation)
11. [Sources and licenses](#sources-and-licenses)

## Features

- **Tactics puzzles** — 3000 puzzles from the Lichess database (ratings 600–2800, 70+ themes). The next puzzle is picked
  for your level and weak spots by a rating system (Glicko-2 or Elo) and a player model. Modes: rated puzzles, training one
  theme, reviewing failed puzzles, Puzzle Rush.
- **AI Brain panel** — evaluation bar, arrows for the best three moves, candidate lines, live search statistics, a mini
  search tree and a plain-language stream of thoughts. A "Why this puzzle?" pop-up explains each choice of puzzle.
- **Game against the coach** — a coach with adjustable strength (400–2900 Elo, the top being the full engine). It
  classifies each of your moves (brilliant, best, good, inaccuracy, mistake, blunder), explains what the move does and what
  was better, and shows an advantage graph and accuracy after the game. Games can be reviewed later and exported as PGN.
- **15 opening lessons** with an explanation of every move, and an opening name recognized live in every game.
- **"Your level"** — after 10 calibration games the coach plays at a strength matched to your results and adjusts it every
  5 games.
- **"How the AI works" page** — a live comparison of minimax and alpha-beta on the real engine and a step-by-step
  alpha-beta demonstration.
- Statistics and rating charts, dark and light theme, three board colours, English and Polish interface, sounds
  synthesized in code, drawn arrows and square marks (right mouse button), pre-moves, a window that scales from a small
  window to 4K.

## Installation and running on Windows

These steps are for Windows 10 or 11 (64-bit). You do **not** need a C compiler or Node.js.

### 1. What you need

| Requirement | Notes |
|---|---|
| **Python 3.11 or newer** | Download from <https://www.python.org/downloads/windows/>. In the installer tick **"Add python.exe to PATH"**. The game is tested in CI on Python 3.11 and 3.14. |
| **Microsoft Edge WebView2 Runtime** | Draws the game window. It comes with Windows 11 and with up-to-date Windows 10, so you most likely have it already. If the game says the window cannot open, install the "Evergreen" runtime from <https://developer.microsoft.com/microsoft-edge/webview2/>. |
| **Git** (optional) | <https://git-scm.com/download/win>. Without it you can download the code as a ZIP file. |
| A C compiler | **Not needed.** The repository ships a ready-made engine library for Windows x64 (see [step 6](#6-optional-build-the-engine-for-your-own-cpu)). |

Check Python in a terminal (PowerShell or Command Prompt):

```powershell
py --version
```

It should print `Python 3.11.x` or higher.

### 2. Get the code

With Git:

```powershell
git clone https://github.com/Snolfed/tacticmind.git
cd tacticmind
```

Without Git: open <https://github.com/Snolfed/tacticmind>, click **Code → Download ZIP**, extract the archive, then open a
terminal in the extracted `tacticmind` folder (in File Explorer: right-click in the folder → **Open in Terminal**).

### 3. Create a virtual environment

A virtual environment keeps the game's libraries separate from the rest of your Python. Run this once, in the project folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

The prompt now starts with `(.venv)`. If PowerShell says that running scripts is disabled, allow it for this window only and
activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

In Command Prompt (cmd) use `.venv\Scripts\activate.bat` instead.

### 4. Install the libraries

```powershell
python -m pip install -r requirements.txt
```

This installs `chess` (python-chess, used only by the interface layer), `pywebview` (the game window; on Windows it also
pulls in `pythonnet`) and `pytest` (for the tests). It takes about a minute.

### 5. Start the game

```powershell
python main.py
```

A game window opens with the start screen. Closing the window ends the game (in the terminal you can also press `Ctrl+C`).

To check which engine the game uses:

```powershell
python -c "from tacticmind.engine import native; lib = native.load(); print(lib.path if lib else 'Python engine (fallback)')"
```

A path ending in `tmengine.dll` means the fast C engine with the NNUE network is in use. `Python engine (fallback)` means
the C library could not be loaded: the game still works, but the engine is 20–30 times slower (see
[Troubleshooting](#troubleshooting)).

**Next time** you only need to open a terminal in the project folder and run:

```powershell
.venv\Scripts\Activate.ps1
python main.py
```

or, without activating anything, `.venv\Scripts\python.exe main.py`. To update to a newer version of the code, run
`git pull` (or download the ZIP again) and, if `requirements.txt` changed, `python -m pip install -r requirements.txt`.

### 6. (Optional) Build the engine for your own CPU

The prebuilt `tmengine.dll` is compiled for any x86-64 processor from about 2009 on. If you have a MinGW-w64 `gcc` on your
`PATH` (for example from [MSYS2](https://www.msys2.org/)), the game compiles the engine itself on the first start (about 2
seconds) for your exact processor, which is a little faster. You can also do it by hand:

```powershell
python scripts/build_engine.py
```

The result goes to `tacticmind\engine\native\build\`. Only `gcc`, `clang` or `cc` (or the compiler named in the `CC`
variable) are recognized, not Visual Studio's `cl`. If the build fails, the game falls back to the prebuilt library.

### 7. (Optional) Run the tests

```powershell
python -m pytest
```

All tests should pass (185 tests, about a minute).

### Where the game keeps your data

Rating, history, statistics and saved coach games are in `%USERPROFILE%\.tacticmind\profile.json`, interface settings in
`%USERPROFILE%\.tacticmind\ui_settings.json`. Delete the files (or the folder) to start from scratch. Another folder can be
chosen with the `TACTICMIND_HOME` environment variable.

## Linux and macOS

Requirements: **Python 3.11+**. On macOS the window needs nothing extra. On Linux the game window needs WebKitGTK and the
system GTK bindings for Python:

| System | Command |
|---|---|
| Arch / Manjaro | `sudo pacman -S --needed python-gobject webkit2gtk-4.1` |
| Debian / Ubuntu / Mint | `sudo apt install python3-gi gir1.2-webkit2-4.1` |
| Fedora | `sudo dnf install python3-gobject webkit2gtk4.1` |

```bash
git clone https://github.com/Snolfed/tacticmind.git
cd tacticmind
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py                     # or: python -m tacticmind
```

The C engine compiles itself on the first start (about 2 s) when a compiler is installed: `gcc` on Linux
(`sudo apt install build-essential`), `clang` on macOS (`xcode-select --install`). Without a compiler the game uses the
slower Python engine. Manual build: `python scripts/build_engine.py`.

On Linux, when a Chromium-based browser (Chromium, Chrome, Brave, Edge or Vivaldi) is installed, the game opens in that
browser's bare app window (no tabs, no address bar, its own profile in `~/.tacticmind/window`), because it follows the
monitor's refresh rate better than WebKitGTK. `TACTICMIND_BROWSER=brave` picks a browser and `TACTICMIND_WINDOW=webview`
forces the pywebview window. If `python main.py` cannot open a window it prints what is missing.

## Using the game

`python main.py` starts a local server on `127.0.0.1` (a free port) and shows the game in its own window.

- **Start screen**: "Tactics puzzles", "Play the coach", "Statistics", "How the AI works". The same places are in the top bar.
- **Puzzle**: the opponent makes the first move, then you find the best one. Move pieces by dragging or by clicking the
  piece and then the target square. Buttons: Hint, Show solution, Try again, Next puzzle. The ◀ ▶ buttons (or the
  ← → keys) step through the moves. The chip above the puzzle ("Rated ▾") switches between rated puzzles, theme
  training, mistake review and Puzzle Rush.
- **AI Brain** has three modes: *Hidden* (only counters while you solve), *Hint* (highlights the piece to move, halves the
  rating reward) and *Full* (everything, once the puzzle is over). Click a candidate line to replay it on the board.
- **Coach**: choose the coach's strength with a slider, pick a colour and play. After a mistake you can take the move back
  and fix it. After the game you get a summary, the advantage graph, a move-by-move review and a PGN export.
- **Drawing**: right mouse button from square to square draws an arrow, a right click highlights a square (Shift = red,
  Ctrl = blue, Alt = lime).
- **Other keys**: F11 full screen, F3 FPS counter. Settings (gear in the top bar): frame limit, dark or light theme, board
  colours. The speaker icon and slider control the volume. EN / PL switches the interface language.

The full description of every screen and mode is in [docs/gameplay.md](docs/gameplay.md).

## Troubleshooting

**Windows**

| Problem | What to do |
|---|---|
| `py` or `python` is "not recognized", or opens the Microsoft Store | Install Python from python.org with "Add python.exe to PATH" ticked, then open a new terminal. If `python` still opens the Store, turn off the "python.exe" entries in Settings → Apps → Advanced app settings → App execution aliases. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window, or use `.venv\Scripts\activate.bat` in cmd, or skip activation and run `.venv\Scripts\python.exe main.py`. |
| `No module named 'chess'` or `'webview'` when starting | The virtual environment is not active or the libraries are not installed. Activate it (step 3) and run `python -m pip install -r requirements.txt`. |
| `pip install` fails while installing `pythonnet` | pywebview needs `pythonnet` on Windows, and it may not have a build for your Python version yet. Install Python 3.12, delete the `.venv` folder and create the environment again with `py -3.12 -m venv .venv`. |
| The game prints a message and no window opens | The message says what is missing. Usually the WebView2 Runtime: install it (see step 1). |
| The AI is slow or weak ("Python engine (fallback)") | Run the engine check from step 5. The C library is probably blocked or missing: check that `tacticmind\engine\native\prebuilt\windows-x64\tmengine.dll` exists (restore it with `git checkout -- tacticmind/engine/native/prebuilt`) and that you run a 64-bit Python (`py -c "import struct; print(struct.calcsize('P')*8)"` should print 64). |

**Linux**

| Problem | What to do |
|---|---|
| "needs WebKitGTK and the GTK bindings" | Install the packages from the [Linux table](#linux-and-macos). Create the `.venv` with the system Python so that it can use the system PyGObject. |
| The window closes immediately with "Error 71 (Protocol error)" (Wayland + NVIDIA) | The game switches NVIDIA's explicit sync off by itself. If it still happens, start with `WEBKIT_DISABLE_DMABUF_RENDERER=1 python main.py` (slower, but works everywhere). |
| Animations are limited to 60 FPS | Install a Chromium-based browser: the game then uses its app window, which follows the monitor's refresh rate. |

**Everywhere:** `TACTICMIND_ENGINE=python` forces the Python engine (useful for comparing), `python main.py --help` lists
the launch options (`--no-window`, `--port`).

## Project structure

```
main.py                     # entry point: starts the server and the game window
tacticmind/
  engine/                   # the chess engine: C sources in native/ (bitboards, PVS search, NNUE),
                            #   ctypes loader (native.py), Python engine (board, movegen, search, eval…)
  rating/                   # Elo, Glicko-2, player model, puzzle selector, profile
  puzzles/                  # puzzle loader, themes, solution validator, puzzle session
  coach/                    # coach: opening book, playing strength, move classes, explanations, game archive
  brain/                    # the "stream of thoughts" and SAN notation in the interface language
  i18n/                     # English and Polish translations
  web/                      # local server (HTTP + SSE) and game window; static/ = built interface
  data/                     # puzzles.json (3000 puzzles), starter_puzzles.json (50)
web/                        # the interface source: React 19 + TypeScript + Vite
scripts/                    # engine build, puzzle builder, benchmarks, matches, NNUE trainer, piece tracing
tests/                      # pytest tests (the interface has its own vitest tests in web/src)
docs/                       # detailed documentation
requirements.txt            # libraries needed to play (+ pytest); requirements-dev.txt adds ruff and mypy
```

Game logic and the engine are pure Python/C modules without any interface code. The game state lives in Python; the
TypeScript interface only draws snapshots of it and sends back moves and clicks. The engine runs in a separate process so
the interface never stutters. See [docs/architecture.md](docs/architecture.md) for the full tree and diagrams.

## How it works

| Part | Short description | Details |
|---|---|---|
| Engine | Negamax with alpha-beta in the PVS variant, iterative deepening, quiescence search, transposition table (Zobrist hashing), move ordering (MVV-LVA, killers, history), MultiPV. The C version adds null move, late move reductions, futility pruning, SEE and singular extensions. | [docs/algorithms.md](docs/algorithms.md) |
| Evaluation | NNUE network (768 → 2×256 → 8 output buckets), trained in this project on 27 M positions from the engine's self-play over four rounds. The hand-written evaluation (tapered piece-square tables, mobility, king safety, pawn structure) is used by the Python engine and as the starting point of the training. | [docs/algorithms.md](docs/algorithms.md#c-engine-and-nnue-network) |
| Rating | Glicko-2 (default) or Elo; the puzzle is an opponent with its own rating. | [docs/algorithms.md](docs/algorithms.md#rating-elo-and-glicko-2) |
| Puzzle selection | Aims at a ~65% chance of success, takes ~30% of puzzles from the weakest themes, eases off after 3 failures, adds a harder bonus puzzle after 5 successes. | [docs/algorithms.md](docs/algorithms.md#puzzle-selection-and-the-player-model) |
| Coach | The same engine with limited depth, softmax sampling among the best moves and occasional random blunders; moves are rated by the drop in win chance (Lichess formula). Explanations are rule-based, with no language model. | [docs/algorithms.md](docs/algorithms.md#coach-playing-strength-based-on-elo) |
| Interface | Python holds the state and sends JSON snapshots over SSE; React draws an SVG board, animations and charts. | [docs/architecture.md](docs/architecture.md) |

The decisions behind the design and the history of the project are in [docs/design-decisions.md](docs/design-decisions.md).

## Results

**Engine strength.** `scripts/match.py` plays matches with 30 openings, both colours, one thread per engine. Against
Stockfish 16 with limited strength (`UCI_Elo`; 100 games per level at 10 s + 0.1 s) the engine scores 92.5% at 2400,
76% at 2700 and 35% at 3000. The best-fitting rating is **about 2890 Elo** (95% interval 2840–2940) on Stockfish's
`UCI_Elo` scale; this is an approximation, because the matches were played at a faster time control than that scale is
calibrated for. Stockfish is used only as an opponent for measuring: it is not part of the game and does not provide
evaluations for training. The engine beat the old Python engine 20 : 0. The network history and all match tables are in
[docs/algorithms.md](docs/algorithms.md#strength-measurements).

**Minimax vs alpha-beta** (same position, same depth, same evaluation, no quiescence; the Italian Game, 31 legal moves):

| Depth | Minimax | Alpha-beta | Alpha-beta + move ordering |
|---:|---:|---:|---:|
| 3 | 32 072 nodes | 2 762 | 2 076 |
| 4 | 1 040 115 nodes (33 s) | 60 313 (1.9 s) | 15 488 (0.5 s) |

All three return the same move and evaluation; only the number of visited nodes differs. The measurements come from
`scripts/benchmark.py` (CPython, one core). More positions are in [docs/algorithms.md](docs/algorithms.md#benchmarks-minimax-vs-alpha-beta).

**Speed.** The C engine searches roughly 0.5–1.7 million nodes per second on one core (depending on the CPU), about 20–30
times more than the Python engine.

## Tests and code quality

```powershell
python -m pytest                   # 185 tests: engine (perft, mates), rating, puzzles, coach, server, translations
```

The interface has its own tests (vitest; they need Node.js 22):

```powershell
cd web
npm install
npm test
```

The Python code is checked with `ruff` and `mypy` (type annotations on every function):

```powershell
python -m pip install -r requirements-dev.txt
ruff check .
mypy tacticmind scripts main.py --disallow-untyped-defs
```

GitHub Actions (`.github/workflows/ci.yml`) runs ruff, mypy and pytest on Python 3.11 and 3.14 on every pull request and
push to `main`, and for the interface vitest, the build and a check that the committed `tacticmind/web/static` matches
`web/src`. A table of what each test file checks is in [docs/development.md](docs/development.md#tests).

Working on the interface (Node.js is needed only for that, not for playing), rebuilding the puzzle set from the Lichess
database and the other scripts are described in [docs/development.md](docs/development.md).

## Documentation

| File | Contents |
|---|---|
| [docs/gameplay.md](docs/gameplay.md) | every screen and mode of the game in detail |
| [docs/architecture.md](docs/architecture.md) | directory tree, client–server design, engine protocol, diagrams |
| [docs/algorithms.md](docs/algorithms.md) | search, evaluation, NNUE, rating, puzzle selection, coach, strength measurements, benchmarks |
| [docs/development.md](docs/development.md) | interface development, tests, puzzle database, scripts, environment variables |
| [docs/design-decisions.md](docs/design-decisions.md) | the reasons behind the main decisions and the stages of the project |
| [scripts/nnue/README.md](scripts/nnue/README.md) | training the NNUE network |
| [PROMPT.md](PROMPT.md) | the original project specification |

## Sources and licenses

- C engine and NNUE network: code and weights written and trained in this project. Descriptions of the techniques (magic bitboards,
  PVS, null move, LMR, SEE, NNUE) — [Chess Programming Wiki](https://www.chessprogramming.org/). Stockfish
  (GPL-3.0) is used only as an opponent in `scripts/match.py` to measure strength; it is not part of the game
  and does not provide evaluations for training the network.
- Puzzles: [Lichess puzzle database](https://database.lichess.org/#puzzles), license **CC0** (public domain).
  Each puzzle has a link to its source game (`url`).
- Perft values: [Chess Programming Wiki — Perft Results](https://www.chessprogramming.org/Perft_Results).
- Glicko-2: M. E. Glickman, *Example of the Glicko-2 system* (glicko.net).
- Piece-square tables based on the "Simplified Evaluation Function" (T. Michniewski, Chess Programming Wiki),
  extended with endgame values.
- Fonts: Space Grotesk, Space Mono and Bricolage Grotesque (SIL Open Font License 1.1, files from Fontsource) and Noto
  (Google) — licenses in `tacticmind/assets/fonts/`.
- Pieces: drawn for this project by Juras (`scripts/pieces_sheet.png`), upscaled 4× with
  [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD-3-Clause; `scripts/pieces_sheet_4x.png`) and traced by `scripts/trace_pieces.py`.
- Libraries: [python-chess](https://python-chess.readthedocs.io/) (GPL-3.0, interface layer only),
  [React](https://react.dev/) and [Vite](https://vite.dev/) (MIT), [pywebview](https://pywebview.flowrl.com/) (BSD-3-Clause).
