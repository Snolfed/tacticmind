# Training the NNUE network for TacticMind

The network in `tacticmind/engine/native/tacticmind.nnue` is trained entirely within this project, on positions from the
TacticMind engine's self-play games. We use no third-party networks and no evaluations from other engines (Stockfish serves
only as an opponent in `scripts/match.py` for measuring strength).

## Architecture

```
768 features (color × piece × square) ──► 256 neurons ─┐
   from the side-to-move perspective                   ├─► SCReLU ─► 512 → 1 (output × 400 = centipawns)
768 features (opponent's perspective) ──► 256 neurons ─┘   (same first-layer weights)
```

- The **accumulator** (first layer) is updated incrementally: a move changes 2–4 features, so we add
  and subtract only 2–4 weight columns of 256 numbers each instead of computing 768 × 256 from scratch (`position.c`, `nnue.c`).
- **SCReLU**: `clamp(x, 0, 1)²`.
- **Output buckets**: 8 output layers, selected by the number of pieces on the board (`(pieces − 2) · 8 / 31`).
  Building the trainer with `-DBUCKETS=1` gives a single layer (the old file format, version 1).
- **Quantization**: first-layer weights × 255 (int16), output weights × 64 — inference uses integers only.

## Training cycle (bootstrapping)

1. **Generation 0** — games with the hand-crafted evaluation (HCE), about 5000 nodes per move, 8–9 random half-moves at the start:
   ```bash
   python scripts/build_engine.py
   ./tacticmind/engine/native/build/tmengine datagen gen0.bin 10000 5000 1 hce   # file, games, nodes, seed, eval
   ```
   We save only quiet positions (not in check, best move is not a capture) with the engine's evaluation and the game result.
   Several processes with different seeds = several cores.
2. **Training**:
   ```bash
   gcc -O3 -march=native -fopenmp scripts/nnue/train.c -o train -lm
   ./train -o net1.nnue -e 20 -l 1.0 gen0_*.bin
   ```
   Target = `λ · sigmoid(eval / 400) + (1 − λ) · game result`, loss = squared error, optimizer Adam.
   On our data λ = 1 (engine evaluations only) works best: the results of games with a random start are too
   noisy. The first network trained with λ = 1 beat the hand-crafted evaluation 78:22 (+220 Elo), while with λ = 0.5 it lost 12:88.
3. **Further generations** — data from engine games played with the new network (`datagen gen1.bin … net1.nnue`), training on
   the new data, a match of the new network against the old one (`scripts/match.py`). Each generation has better evaluations in its data, so
   the next network is stronger.

## Network history in the repository

| Data generation | Who played | Positions | Network |
|---|---|---:|---|
| 0 | hand-crafted eval (HCE) | 2.2 M | network 1 (+220 Elo vs. HCE) |
| 1 | network 1 | 10.0 M | network 2 (gen. 0–1, +193 vs. network 1) |
| 2 | network 2 | 7.9 M | network 3 (gen. 0–2, +76 vs. network 2) |
| 3 | network 3 | 7.3 M | **network 4** (gen. 0–3, buckets, +30 vs. network 3) — current |

Each generation: 4 `datagen` processes at 5000 nodes per move, about 700 positions/s combined. Training network 4
(27.3 M positions, 20 epochs, 2 threads): about 70 minutes. Match results and the comparison with Stockfish are in [docs/algorithms.md](../../docs/algorithms.md).
A network with 512 neurons (same data as network 3) had a lower loss, but in a timed match it came out even
(−10 ± 40 Elo) — it is twice as slow. With much more data it is worth trying again.

Data record format (32 bytes): occupancy bitboard, piece codes at 4 bits each, evaluation from White's perspective (int16),
result (0 / 1 / 2 = Black wins / draw / White wins), side to move.
