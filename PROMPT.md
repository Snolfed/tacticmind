# TaktykAI: chess puzzles with an AI that thinks out loud

## Context

You are building a university programming project: a game that uses an artificial intelligence algorithm. The game is a chess tactics trainer in the style of chess.com "Puzzles". Two things set it apart:

1. **Its own chess engine (AI)**, whose "thoughts" are visible live in a panel next to the board.
2. **Adaptive difficulty**: the game computes the player's Elo rating from their solutions and picks the next puzzles to match their current level.

**The most important grading criterion:** the AI algorithm must be **written from scratch in this project**. Neither Stockfish nor any other ready-made engine may be the "brain" of the game. The algorithm must be clearly visible in action and easy to explain at the project defense. The code must be readable, with comments in key places, and the algorithms must be described in the README.

## Tech stack

- Vite + React + TypeScript (strict mode) + Tailwind CSS
- Board: `react-chessboard` (drag-and-drop and click-click)
- `chess.js` **only in the UI layer** (validating the player's moves, SAN notation, FEN). The AI engine has its own board representation and its own move generator.
- The engine runs in a **Web Worker**, so the interface never stutters
- Charts: Recharts
- Tests: Vitest
- Saving progress: localStorage. No backend; everything works offline after `npm run dev`.
- The entire interface in Polish

## 1. AI engine (the heart of the project): `src/engine/`

Implement from scratch:

- **Board representation** 0x88 (or 10x12 mailbox). State: side to move, castling rights, en passant square, halfmove clock. FEN parsing and generation.
- **Move generator** with the full rules: castling, en passant, promotion to all 4 pieces, detection of check, checkmate and stalemate, make/unmake move.
- **Perft** to verify the generator (the tests below must pass).
- **Search:**
  - negamax with alpha-beta pruning,
  - iterative deepening with time and depth limits,
  - quiescence search (captures) to avoid the horizon effect,
  - move ordering: PV move first, then captures by MVV-LVA, killer moves, history heuristic,
  - transposition table with Zobrist hashing,
  - mate scores with distance to mate (a faster mate is better).
- **Evaluation function:** material + piece-square tables in a tapered version (separate middlegame and endgame values), bonuses for king safety and mobility. In the UI the evaluation is always shown from White's perspective, in pawns (e.g. +1.5) or as a mate (M3).
- **MultiPV:** computing the 3 best candidate moves together with their lines.
- **Search statistics** collected live: depth, node count, nodes/s, number of alpha-beta cutoffs, TT hits, time, principal variation (PV).
- **Worker protocol:** after each completed depth the worker sends the UI a message `{ depth, scoreCp | mateIn, pv, multiPv, nodes, nps, cutoffs, ttHits, timeMs }`. It handles a `stop` command and new requests without restarting the worker.
- **Comparison mode** (for the defense): the same position computed with plain minimax and with alpha-beta at the same depth, showing how many nodes were saved.

## 2. The "AI Brain" panel: what the AI is thinking

The panel sits to the right of the board, and below it on a phone. It contains:

- **Eval bar** next to the board, as on chess.com. Animated, with a value such as +1.5 or M3.
- **3 best candidate moves** with an evaluation and a line in SAN, e.g. `1. Hxf7+ Kxf7 2. Sg5+ Kg8 3. Sxe6`. Clicking a line replays it on the board in preview mode.
- **Arrows** on the board: the best move in green, the second and third semi-transparent.
- **Live counters:** depth, nodes, nodes/s, pruned branches, time.
- **"Stream of thought":** a log of Polish sentences generated from search data using templates, with no external LLM. Examples:
  - "Depth 4: Hxf7+ looks best (+3.2). After Kxf7 Sg5+ I win the queen."
  - "I'm changing my mind! At depth 6 I see mate in 3 after Wd8+."
  - "Thanks to alpha-beta I skip 84% of the branches."

  Clearly mark every change of the best move between depths. This shows that the AI really "thinks".
- **Mini search tree** (bonus): the first 2 levels of the tree with evaluations. Branches pruned by alpha-beta are greyed out or struck through.
- **Visibility modes**, so the panel does not give away the solution:
  - *Hidden*: while solving, only the statistics and the fact that the AI is computing are visible. Moves and evaluation are hidden.
  - *Hint*: a button highlights the piece that has to move. It reduces the rating reward.
  - *Full*: after solving or failing everything is visible, and the AI explains the puzzle.

## 3. Chess puzzles

- Source: **the Lichess puzzle database** (CC0 license): https://database.lichess.org/lichess_db_puzzle.csv.zst
  Columns: `PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags`.
- The script `scripts/build-puzzles.ts` selects about 3000 puzzles from the downloaded CSV, evenly distributed over the 600–2800 range (buckets of 100 points). It takes only puzzles with `Popularity > 80` and `NbPlays > 500` and writes them to `src/data/puzzles.json`.
- Include a small starter set in the repository (about 50 real puzzles from the Lichess database, with varied ratings and themes), so the app works without downloading the whole database.
- **Beware of the Lichess format:** `FEN` is the position **before** the opponent's move. The first move in `Moves` is played by the opponent (with an animation); only then does the player start solving. Moves are written in UCI. The player plays the side to move after that first move, so flip the board to their side.
- Play the opponent's replies during the puzzle automatically, with a delay of about 400 ms.
- **Alternative solutions:**
  - if the player's move differs from the reference move but delivers mate, the puzzle is solved,
  - if according to the engine the move still clearly wins (e.g. evaluation > +3 and at most 50 cp worse than the best), show "Good move, but there is a better one. Try again" and do not count it as a mistake.
- **Themes**: translate them into Polish and show them after solving: fork → widełki, pin → związanie, skewer → przeszycie, discoveredAttack → odsłona, sacrifice → poświęcenie, deflection → odciągnięcie, attraction → przyciąganie, backRankMate → mat na ostatniej linii, hangingPiece → wisząca figura, mateIn1/2/3 → mat w 1/2/3, endgame → końcówka, etc.
- **After a wrong move** the AI shows the opponent's reply computed by the engine, e.g. "After Wd1? the opponent plays Hxh2#. Mate." Then the player can choose "Try again" or "Show solution".

## 4. Adaptive Elo rating and puzzle selection

### Player rating

- Start: 1200. The first 10 puzzles are a calibration with a high K factor (e.g. 60). Then K drops to 32, and after 50 puzzles to 20.
- Expected score: `E = 1 / (1 + 10^((R_puzzle − R_player) / 400))`
- Rating change: `ΔR = K · (S − E)`
- The score `S` is not binary:
  - 1.0: solved without a mistake and without a hint,
  - 0.5: solved with a hint,
  - 0.0: a wrong move (even if the player finishes the puzzle afterwards),
  - a slight penalty for a very long time (over 3× the player's average time), at most −0.2.
- Bonus: instead of Elo, implement Glicko-2 with rating deviation (RD) and show the uncertainty interval, e.g. "1450 ± 80".

### Choosing the next puzzle (the second AI element: the player model)

- Aim for about a 65% chance of success (the "flow zone"): target puzzle rating ≈ `R_player − 100`, with a random spread of ±75.
- The **player model** tracks success in each theme (forks, pins, mates…). About 30% of puzzles come from the player's weakest themes.
- **Frustration protection:** after 3 failures in a row the next puzzle is noticeably easier. After 5 successes in a row a "bonus puzzle" about 200 harder appears.
- Puzzles do not repeat, and themes are varied.
- Show every puzzle-selection decision in a "Why this puzzle?" popup, e.g. "Puzzle rating 1380, aiming for a 65% chance. Your weak spot: pins (41%)".

### Rating presentation

- A large rating at the top of the screen with an animated change after each puzzle (+12 in green, −9 in red).
- The puzzle's rating is visible after it is finished (as on chess.com).
- A streak with a fire icon.

## 5. UI/UX in the style of chess.com

- Dark theme (background `#312e2b`), classic green board (`#769656` / `#eeeed2`), last-move highlight, dots on legal-move squares, a piece picker on promotion.
- Move animations and sounds (move, capture, check, success, mistake). Sounds generated with the Web Audio API or files with a license that permits their use.
- Feedback: a green ✓ or red ✗ on the move's target square, plus the messages "Best move!" and "Sorry, that's not it".
- Buttons: Hint, Show solution, Try again, Next puzzle, and an AI-panel mode toggle.
- Statistics screen: rating chart over time, success rate per theme (radar or bar chart), number of puzzles, best streak, average time.
- Responsiveness: on desktop the board with the panel beside it; on a phone the panel below the board and a horizontal eval bar above it.
- A start screen with the game's name and the buttons "Play", "Statistics" and "How does the AI work?". The last page explains the algorithms for the instructor and includes an interactive comparison of minimax and alpha-beta.

## Architecture

```
src/
  engine/    # own engine: board.ts, movegen.ts, eval.ts, search.ts, zobrist.ts, tt.ts, worker.ts
  rating/    # elo.ts (or glicko2.ts), selector.ts, playerModel.ts
  puzzles/   # loader.ts, themes.ts (translations), validator.ts
  ui/        # Board, EvalBar, AIBrainPanel, ThoughtStream, SearchTree, RatingBadge, StatsPage…
  hooks/     # useEngine.ts (communication with the worker), usePuzzleSession.ts
  data/      # puzzles.json
scripts/build-puzzles.ts
tests/
```

Game logic and the engine are separated from the React components: pure functions, easy to test.

## Tests (Vitest): must pass

- Perft from the starting position, depths 1–4: 20, 400, 8,902, 197,281.
- Perft "Kiwipete" `r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1`, depths 1–3: 48, 2,039, 97,862.
- Perft "position 3" `8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1`, depths 1–4: 14, 191, 2,812, 43,238.
- The engine finds mate in 1, 2 and 3 in several known positions.
- At a small depth, alpha-beta returns the same result as plain minimax but visits fewer nodes.
- Elo: correct E and ΔR for sample values. The puzzle selector hits the target rating range.

## Work stages

Work in stages. After each stage the app must start (`npm run dev`) and the tests must pass. At the end of each stage, briefly summarize what you did.

1. Project skeleton, board, loading the starter set, solving puzzles (no AI or rating yet).
2. Engine: board, move generator, perft tests.
3. Search, evaluation function, worker, mate tests.
4. "AI Brain" panel: eval bar, arrows, stream of thought, visibility modes.
5. Elo rating, player model, puzzle selection, "Why this puzzle?" popup.
6. Statistics, start screen, "How does the AI work?" page, sounds, animations, responsiveness.
7. The `build-puzzles.ts` script and the README.

## README: documentation for the defense

The README, in Polish, contains:

- a description of the game and instructions for running it,
- a description of the algorithms: minimax, alpha-beta (with pseudocode), iterative deepening, quiescence search, transposition table, evaluation function, Elo/Glicko, puzzle selection,
- an architecture diagram (Mermaid),
- a table of measurements: node counts for minimax, alpha-beta and alpha-beta with move ordering at depths 1–5,
- a "Design decisions" section,
- sources (Lichess puzzle database, CC0).

## Rules

- No placeholders or "TODO: implement". Every function must work.
- TypeScript strict, no `any`.
- Do not use Stockfish or any other ready-made engine to compute the AI's moves.
- If something is unclear or you have to choose between two approaches, pick the more sensible one, record the decision in the README under "Design decisions", and keep going.
