# Algorithms

How the engine, the rating system and the coach work. The code of the Python engine is meant to be readable; the C engine (last part) is the one used in the game.


## 0x88 board representation and move generator

The board is an array of 128 squares (16 files × 8 ranks); only files 0–7 are used. Index = `rank·16 + file`.
The 0x88 trick: a square is on the board if and only if `(square & 0x88) == 0` — a single bitwise operation
detects stepping off the board. Based on this, at start-up we compute once the square lists for knights, the king
and bishop/rook rays that the generator uses. A move is a single integer
(from square, to square, promotion piece, flags: capture, en passant, castling, pawn double push).

The generator produces pseudo-legal moves (with castling, en passant and promotions to 4 pieces), and legality
is checked after making the move: if our own king is attacked, the move is undone (`make_legal_move`).
`make_move`/`unmake_move` push onto a stack everything that cannot be restored from the move (the captured piece,
castling rights, the en passant square, the 50-move counter, the hash). The generator's correctness is confirmed by **perft** —
the number of leaves of the move tree matches the reference values for 5 positions (tests in `tests/test_perft.py`).

## Minimax (negamax)

We assume both sides play perfectly: we maximize the evaluation, the opponent minimizes it. The
**negamax** formulation uses the identity `max(a, b) = −min(−a, −b)`: the evaluation of a position for the side to move is minus
the opponent's best evaluation after each of our moves. A single function is enough.

```
function negamax(position, depth):
    if depth == 0: return evaluate(position)          # from the side to move's perspective
    best = −∞
    for each legal move:
        make move
        best = max(best, −negamax(position, depth − 1))
        unmake move
    if no moves: return (in check ? −MATE + ply : 0)   # checkmate or stalemate
    return best
```

Minimax visits about `b^d` nodes (b ≈ 30–35 moves, d = depth) — at depth 5 that is tens of millions.

## Alpha-beta

Alpha-beta gives **the same result** as minimax, but skips branches that cannot change the decision.
`α` = the score the side to move is already guaranteed; `β` = the best score its opponent will allow.
When some move scores ≥ β, the opponent will not allow this position — the remaining moves are not searched
(**β cutoff**).

```
function alphabeta(position, depth, α, β, ply):
    if draw (repetition, 50 moves): return 0
    if in check: depth += 1                           # check extension
    if depth <= 0: return quiescence(position, α, β)
    probe the transposition table (may give a score or the best move right away)
    best = −∞
    for each move in order: TT/PV, MVV-LVA captures, killers, history:
        if move is illegal: skip
        make move
        score = −alphabeta(position, depth − 1, −β, −α, ply + 1)
        unmake move
        if score > best:
            best = score
            if score > α:
                α = score; store the line (PV)
                if score >= β:                        # β cutoff
                    record the move as killer/history; break the loop
    if no legal moves: return (in check ? −MATE + ply : 0)
    store in TT (exact / lower bound / upper bound)
    return best
```

With perfect move ordering alpha-beta visits about `b^(d/2)` nodes — in the same time it searches almost
twice as deep. That is why **move ordering** matters so much:

1. the move from the principal variation / transposition table (the best one from the shallower iteration),
2. captures by **MVV-LVA** (most valuable victim, least valuable attacker), queen promotions,
3. **killer moves** — two quiet moves per ply that recently caused a cutoff,
4. **history heuristic** — `depth²` points for moves (piece → square) that caused cutoffs.

Moves are picked lazily (selection sort): after a cutoff the rest of the list is skipped anyway.

## Iterative deepening

The engine searches depth 1, then 2, 3… until the time or depth limit. Shallow iterations are cheap, and their
best line orders the moves in the deeper one — this yields more cutoffs than a single search
straight at the target depth. After each completed depth the engine sends the result to the interface
(hence the live "thoughts"). A new depth is not started if more than half of the time has been used.
When a mate in `n` plies is found and the depth is ≥ `n`, the search stops (there is no shorter mate).

## Quiescence search

An evaluation in the middle of an exchange is misleading (e.g. the queen has just captured a pawn but is about to be captured) — this is the **horizon
effect**. So at the leaves we play out captures and promotions until the position is quiet:

```
function quiescence(position, α, β):
    if in check: consider all moves (so as not to miss a mate)
    else:
        stand_pat = evaluate(position)                 # the side to move may decline to capture
        if stand_pat >= β: return stand_pat
        α = max(α, stand_pat)
    for each capture/promotion (MVV-LVA):
        skip captures that cannot raise α (delta pruning)
        skip "bad captures" (a more valuable piece takes a cheaper one on a defended square)
        score = −quiescence(after the move, −β, −α)
        update α, cut off when score >= β
```

The benchmark table below (without quiescence, fixed depth) shows the horizon effect clearly: the opening evaluation
jumps between −2.1 and +1.4 depending on whether the depth ends in the middle of an exchange.

## Transposition table and Zobrist hashing

Each piece on each square, the side to move, castling rights and the en passant square are assigned a random
64-bit number (fixed seed). The position hash is the XOR of these numbers; on a move it is updated with a few XOR operations.
The transposition table (`tt.py`) stores for a hash: depth, evaluation, evaluation type (**exact**, **lower**
bound after a β cutoff, **upper** bound when no move improved α) and the best move. Mate scores are stored
relative to the current node (not the root), so that the distance to mate stays correct when read at a different depth.
The hashes are also used to detect position repetitions (draws).

## Mate scores

A mate scores `±(32000 − number of plies from the root)`, so **a faster mate is always better**, and when
defending the engine picks the longest path to mate. The interface shows this as `M3` / `−M2`.

## Evaluation function

Evaluation in centipawns (100 = a pawn):

- **material** and **piece-square tables** (PST) — separate values for the middlegame (mg) and the endgame (eg),
- **tapered eval** — score = `(mg·phase + eg·(24 − phase)) / 24`, where the phase depends on the pieces on the board
  (knight/bishop 1, rook 2, queen 4). In the middlegame the king hides, in the endgame it heads to the centre,
- **mobility** — a bonus for every available square above the typical count (separately per piece and phase),
- **king safety** — the pawn shield in front of the king, a penalty for open/half-open files, "tropism" (enemy
  pieces close to the king),
- **pawn structure** — doubled, isolated, passed (the bonus grows with every rank),
- **bishop pair**, detection of draws by insufficient material.

The board sums material and PST incrementally in `make_move`, so a leaf only pays for the terms that depend on the piece layout.
For the engine the evaluation is from the side to move's perspective (a requirement of negamax); the interface always shows it
**from White's perspective** (e.g. +1.5 or M3).

## MultiPV (3 best moves)

Instead of searching the root three times, we do it in a single pass: for each subsequent root move α = the score of the
**third** best move found so far. Moves in the top three thus get exact scores
and lines, while worse ones are quickly cut off (fail-low).

## Statistics and the mini tree

The engine keeps live counts of: depth (and maximum selective depth), nodes, nodes/s, β cutoffs, TT hits,
the share of skipped moves and time. For the last depth it records the first two levels of the tree: the root moves
with their scores (exact, or "≤" after a fail-low) and the opponent's replies — branches cut off by alpha-beta
are greyed out and struck through in the panel.

## Stream of thoughts

`brain/thoughts.py` turns successive engine results into sentences in the interface language using templates (no LLM at all),
e.g. "Depth 4: still Qxf7+ (+3.2). After Kxf7 Ng5+ I win the queen.", "I'm changing my mind! At depth 6 I see
mate in 3 after Rd8+.", "Thanks to alpha-beta I skip 84% of the branches.". The comment about winning material comes from counting
the material at the end of the PV line. A change of the best move between depths is highlighted in colour.

## Rating: Elo and Glicko-2

A puzzle is treated as an opponent with the puzzle's rating.

- Expected score: `E = 1 / (1 + 10^((R_puzzle − R_player) / 400))`
- Elo rating change: `ΔR = K · (S − E)`; K = 60 for the first 10 puzzles (calibration), then 32, after 50 puzzles 20.
- Score `S`: 1.0 — no mistake and no hint; 0.5 — with a hint; 0.0 — a wrong move (even if the player then
  finishes the puzzle) or a revealed solution. Penalty for taking very long: above 3× the player's average time,
  linearly down to −0.2 (at 6×).
- **Glicko-2** (bonus, the default system): besides the rating `r` the player has a deviation `RD` and a volatility `σ`.
  Implemented following Glickman's paper (conversion to the μ/φ scale, variance v, improvement Δ, new volatility
  via the Illinois method, new φ and μ); a test checks the example from the paper (1500/200 → 1464.06 / 151.52).
  One puzzle = one rating period; the puzzle's RD comes from the Lichess database. The interface shows "1450 ± 80"
  (± RD), and the rating chart has an uncertainty band. The system can be switched to Elo in the statistics.

## Puzzle selection and the player model

`rating/selector.py`:

- **flow zone** — we aim for about a 65% chance: puzzle rating ≈ `R_player − 100` (since E(−100) ≈ 0.64)
  with a random spread of ±75,
- the **player model** (`player_model.py`) tracks the success rate in each theme (forks, pins, mates…),
  with Bayesian smoothing (one failed puzzle does not turn a theme into a weak spot); about **30%** of puzzles come
  from the weakest themes,
- **frustration guard** — after 3 failures in a row a clearly easier puzzle (≈ R − 300); after 5 successes
  in a row a **bonus puzzle** (≈ R + 200),
- puzzles do not repeat, and themes from the last 3 puzzles get a penalty (variety),
- every decision has a justification in the **"Why this puzzle?"** pop-up, e.g. "Puzzle rating about 1380, aiming
  for a 65% chance (flow zone). Your weak spot: pin (41%)."
- **theme training** uses the same rules on the puzzles of one theme; the **review queue** (`PlayerProfile.review`, at most
  200 puzzles) gets every failed puzzle and loses it once it is solved cleanly (older profiles rebuild it from the history);
  **Puzzle Rush** ignores the rating: puzzle *n* is drawn from the 6 unused puzzles closest to `600 + 55·n`.

## Coach: playing strength based on Elo

`coach/strength.py`. The coach uses the same engine but plays weaker in three ways:

| Elo | Depth | Time per move | Candidates (MultiPV) | Temperature T | Random move |
|---|---|---|---|---|---|
| 400 | 1 | 0.4 s | 8 | 305 cp | 25% |
| 800 | 2 | 1.0 s | 6 | 174 cp | 14% |
| 1200 | 3 | 1.6 s | 5 | 80 cp | 6% |
| 1600 | 4 | 2.2 s | 4 | 24 cp | 1.6% |
| 2000 | 5 | 2.8 s | 2 | 5 cp | 0% |
| 2300 | 8 | 2.9 s | 1 | — | 0% |
| 2600 | 12 | 3.1 s | 1 | — | 0% |
| 2900 | full (time limit) | 3.2 s | 1 | — | 0% |

From the candidates the coach samples a move with probability `p(move) ~ exp((score − best_score) / T)`
(softmax with temperature T): with a large T a move half a pawn worse is almost as likely as the best one,
with a small T the coach almost always plays the best move. A "random move" is a completely random legal move, like
a beginner's blunder. In the opening the coach plays from the opening book (randomly, weighted by how many lines contain the move).
Above 2000 the coach always plays the engine's best move and only searches deeper with every step (2100 = depth 6 …
2500 = depth 10, then two plies a step); at 2900 it is the engine at full strength, which scored about 2890 against
limited-strength Stockfish (see "Strength measurements"), at a faster time control than the coach's 3 s per move.
The coach's Elo is **approximate** — exact calibration would require thousands of games against players with known ratings.

## Move classification and accuracy

`coach/review.py`. While the player is thinking, the engine analyses the position in the background (MultiPV 3, up to 1.6 s). If the player's move is
among the top three, its score is already known; if not, the engine also searches the position after the move. The score is converted
to a **win chance** (the Lichess formula): `W(cp) = 50 + 50 · (2 / (1 + e^(−0.00368208 · cp)) − 1)` — 0 cp is 50%,
+3 pawns about 75%, mate 100%. The move class depends on how many percentage points the win chance **dropped**
compared to the best move, but at least 1 point per 40 centipawns thrown away (evaluations capped at ±50 pawns; a
forced mate counts as 56), since past about +10 the win chance hardly moves and even a lost queen or a thrown-away
mate would look "excellent": up to 2 — excellent, up to 5 — good, up to 10 — inaccuracy, up to 20 — mistake, above that —
blunder. The engine's best move is "best", and if the second move was worse by ≥ 15 points — "great" (the only
good move; does not apply to obvious captures: a recapture or taking a piece left hanging). "Brilliant" is the engine's
move (or within 1 point of it) that really sacrifices a piece, in a position that was not already winning. A sacrifice is
measured against the safest move in the position: material that every move loses (a trapped piece, two pieces attacked
at once) is not a sacrifice. Thanks to the win-chance scale, the same half-pawn mistake weighs more in an equal
game than at a +8 advantage.

**Accuracy** of a move: `103.1668 · e^(−0.04354 · drop) − 3.1669` (%, as on Lichess). Game accuracy is also Lichess's:
the average of the mean weighted by how sharp the game was around each move and the **harmonic** mean, so a few blunders
among many easy moves pull it down instead of disappearing in the average.
The coach's moves are rated the same way, so the summary shows the accuracy of both sides.

## Coach explanations

`coach/advice.py` — no language model, only rules and engine results:

- **what the move does**: capture, check, castling, promotion, attack on a piece more valuable than the attacker or an undefended one
  (two at once = a fork), moving a piece out of attack, defending a hanging piece, developing a minor piece, a pawn in the centre,
  a rook on an open file,
- **what the opponent threatens**: the engine's line after the player's move — mate ("After this move the opponent mates: 1. Qxf7#")
  or loss of material, counted to the end of the exchange and cut at the move that actually wins material,
- **what was better**: the best move and its line — mate, material gain or the move's features ("develops the knight"),
- **the coach's threats** after its move: mate in one (checked with a "null move") or a hanging piece of the player's.

Comments are stored as data (translation key + parameters), and the text is produced at draw time, so switching
the language mid-game immediately translates earlier comments as well.

## Calibration and "Your level"

`rating/coach_profile.py`. Each game against the coach is one Glicko-2 period: the opponent's rating equals the coach's
Elo with RD = 80 (because that Elo is approximate), the score `S` = 1 / 0.5 / 0 minus 0.1 for each hint and take-back.
After **10 games** "Your level" = the rating rounded to 25 (within 400–2000); after that it is recalculated
**every 5 games**, not after each one — the opponent stays stable, and progress feels like moving up a rank.
Abandoning a game after at least 5 moves counts as resigning (after confirmation); opening lessons count towards
the level only when you keep playing after the lesson and the game ends.

## C engine and NNUE network

The game engine (`tacticmind/engine/native/`) is the same idea as the Python version — negamax with alpha-beta, iterative
deepening, quiescence, a transposition table, MultiPV — but written in C and extended with techniques that only pay off
at millions of nodes per second. The game loads it as a library via `ctypes` (`engine/native.py`),
and `engine/csearch.py` gives it exactly the same interface as the Python `Searcher`: after each depth it produces
the same `SearchInfo` (MultiPV, statistics, mini tree), so the "AI Brain" panel, the coach and puzzle evaluation work unchanged.

**Board and moves.** Bitboards (a 64-bit mask for each piece type), bishop and rook attacks from "magic"
tables (magic numbers found by random search and hard-coded), legality checked without making the move (whether after the move
anything attacks the king). Perft matches the reference values, e.g. Kiwipete at depth 5 = 193 690 690.

**Search** (`search.c`):

- **PVS** — the first move is searched with a full window, the rest with a "zero window" (is it better than α?); a full
  re-search only when a move surprises. With good move ordering this means several times fewer nodes,
- an **aspiration window** at the root (score close to the previous depth),
- **null move pruning** — if the position is ≥ β even after handing the move to the opponent, the branch will certainly cut off,
- **late move reductions** — late, quiet moves are searched shallower (the reduction grows with depth and move number),
- **reverse futility, futility and late move pruning, razoring** — in shallow nodes we skip moves with no chance of
  improving α,
- **SEE** (static exchange evaluation) — pruning losing exchanges and ordering them,
- **singular extensions** — a transposition-table move clearly better than the rest is searched deeper,
- ordering: TT move, good captures (MVV-LVA + SEE), killers, counter-move, history and continuation history.

**NNUE** (`nnue.c`, `position.c`). The evaluation is a small neural network:

```
768 features (colour × piece × square) from the side to move ──► 256 neurons ─┐
768 features from the opponent's side (same weights)          ──► 256 neurons ─┴► SCReLU ─► 512 → 1
                                                                       (8 output layers — by piece count)
```

The output layer is chosen by the number of pieces on the board (8 "buckets" from endgame to opening): the same
features mean something different in the endgame than in the opening, and the cost is zero — only one layer is computed anyway.

The NNUE trick: the first layer (the accumulator) is a sum of weight columns for the pieces on the board, and a move changes only 2–4 pieces.
Instead of 768 × 256 multiplications, each move adds and subtracts 2–4 columns of 256 numbers. The weights are
quantized to integers (int16), so evaluation costs less than the hand-written evaluation function — the engine with the network
searches 0.5–1.7 M nodes/s on a single core (depending on the CPU), about 20–30 times more than the Python engine.

**Where does the network come from?** It is trained entirely in this project (`scripts/nnue/`), with no third-party networks and no evaluations from other engines:

1. the engine with the hand-written evaluation plays itself (8–9 random plies at the start, about 5000 nodes per move);
   quiet positions are saved with the evaluation from the search,
2. a trainer in C (`train.c`, Adam, OpenMP) teaches the network to predict `sigmoid(eval / 400)`,
3. the engine with the new network plays itself again — its evaluations are better, so the next network is too.

## Strength measurements

All matches: `scripts/match.py`, 30 openings played with both colours, one thread per engine,
Elo with a 95% confidence interval.

**Successive networks** (each against the previous one, 200 games, 2 s + 0.02 s per game):

| Network | Training data | Result | Elo |
|---|---|---:|---:|
| 1 | 2.2 M positions from games with the hand-written evaluation | 78 : 22 vs the hand-written evaluation (100 games) | +220 ± 63 |
| 2 | 12 M (+ network 1 games) | 150.5 : 49.5 | +193 ± 40 |
| 3 | 20 M (+ network 2 games) | 121.5 : 78.5 | +76 ± 39 |
| 3 with 512 neurons | the same 20 M | 97 : 103 vs network 3 | −10 ± 40 (more accurate, but 2× slower) |
| 3 with buckets | the same 20 M | 104.5 : 95.5 vs network 3 | +16 ± 37 |
| **4 (in the game)** | **27.3 M** (+ network 3 games), buckets | 108.5 : 91.5 vs network 3 | +30 ± 41 |

**Against Stockfish 16 with limited strength** (`UCI_LimitStrength`, `UCI_Elo`; 100 games per level,
10 s + 0.1 s per game):

| Stockfish `UCI_Elo` | Wins / draws / losses | Score | Elo difference |
|---:|:---:|---:|---:|
| 2400 | 90 / 5 / 5 | 92.5% | +436 ± 136 |
| 2700 | 70 / 12 / 18 | 76% | +200 ± 75 |
| 3000 | 23 / 24 / 53 | 35% | −108 ± 62 |

Best-fitting Elo (maximum likelihood over all 300 games): **about 2890** (95%: 2840–2940)
on Stockfish's `UCI_Elo` scale, which is calibrated to the CCRL 40/4 list. This is an approximation: Stockfish's
calibration refers to a slower time control, while our matches were played faster.

**Against the old Python engine** (300 ms per move): 20 : 0.

To run it yourself (requires `pip install chess` and Stockfish):

```bash
python scripts/build_engine.py
python scripts/match.py --a tacticmind/engine/native/build/tmengine --b stockfish \
    --b-option UCI_LimitStrength=true --b-option UCI_Elo=2700 --tc 10+0.1 --games 100 --concurrency 4
```

## Benchmarks: minimax vs alpha-beta

Same position, same depth and same evaluation function (no quiescence and no transposition table),
so all three variants return an identical result — only the number of visited nodes differs.
Measured with `python scripts/benchmark.py` (CPython 3.14, one core). Minimax at depth 5 in the opening
was skipped — an estimated 28.6 M nodes (a dozen or so minutes in Python).

**Italian Game (middlegame)** — `r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3` (31 legal moves)

| Depth | Minimax | Alpha-beta | Alpha-beta + ordering | Alpha-beta savings | Savings with ordering | Eval |
|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 32 (0.00 s) | 32 (0.00 s) | 32 (0.00 s) | 0.0% | 0.0% | −0.2 |
| 2 | 1 048 (0.04 s) | 660 (0.02 s) | 285 (0.01 s) | 37.0% | 72.8% | +1.3 |
| 3 | 32 072 (1.04 s) | 2 762 (0.09 s) | 2 076 (0.07 s) | 91.4% | 93.5% | −2.1 |
| 4 | 1 040 115 (33.24 s) | 60 313 (1.86 s) | 15 488 (0.48 s) | 94.2% | 98.5% | +1.4 |
| 5 | — (about 28.6 M) | 792 174 (24.84 s) | 73 121 (2.23 s) | — | 90.8% relative to alpha-beta | −1.8 |

**Endgame (position 3 from the Chess Programming Wiki)** — `8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1` (14 legal moves)

| Depth | Minimax | Alpha-beta | Alpha-beta + ordering | Alpha-beta savings | Savings with ordering | Eval |
|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 15 (0.00 s) | 15 (0.00 s) | 15 (0.00 s) | 0.0% | 0.0% | +1.2 |
| 2 | 206 (0.00 s) | 131 (0.00 s) | 30 (0.00 s) | 36.4% | 85.4% | +0.9 |
| 3 | 3 018 (0.05 s) | 503 (0.01 s) | 394 (0.01 s) | 83.3% | 86.9% | +1.5 |
| 4 | 46 256 (0.71 s) | 1 733 (0.03 s) | 1 047 (0.02 s) | 96.3% | 97.7% | −0.1 |
| 5 | 720 880 (11.13 s) | 32 498 (0.49 s) | 6 946 (0.11 s) | 95.5% | 99.0% | +1.8 |

Conclusions:

- at depth 1 there are no cutoffs (the leaves have no siblings to cut), from depth 3 alpha-beta skips > 80% of nodes,
- move ordering brings alpha-beta close to the ideal `b^(d/2)`: at depth 5 in the opening 73 k instead of 792 k nodes,
- the jumping evaluations (−2.1 / +1.4 / −1.8) are the horizon effect at a fixed depth — which is why the actual game engine
  uses quiescence search.

The full engine (with iterative deepening, TT and quiescence) searches about 25–60 k nodes/s in Python; in a typical
puzzle it reaches depth 6–9 in a few seconds, finds mates in 3 in about 0.1 s (depth 3 with the check
extension) and confirms them within 2 s. The same comparison can be run interactively on the "How the AI works" page.
