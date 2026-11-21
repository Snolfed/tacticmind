# Gameplay guide

Everything the game does, screen by screen. The short version is in the [README](../README.md).

## How to play

- **Start screen**: "Tactics puzzles", "Play the coach", "Statistics", "How the AI works". The same places
  are in the top bar: "Puzzles", "Coach", "Statistics", "How the AI works".
- **Puzzle**: the opponent makes the first move (animated), then you look for the best move. The board is
  flipped to your side. You move by dragging or click-click; dots pop up on legal squares (rings close in on pieces
  you can capture), and on promotion
  a piece picker appears. The opponent's replies are played automatically after about 400 ms.
- **Feedback**: a lime ✓ or a red ✗ on the target square and the messages "Best move!" /
  "Sorry, that's not it". After a mistake the engine calculates the opponent's reply, e.g. "After Rd1? the opponent plays Qxh2#. Mate.",
  and you choose "Try again" or "Show solution".
- **Brilliant move (!!)**: if the correct move is a sacrifice (you give up a piece for at least 2 pawns of material,
  e.g. a rook for a pawn), instead of ✓ a cyan "!!" appears with a glow, sparks and the message "Brilliant move!!" —
  just like on chess.com (`puzzles/validator.py: is_sacrifice`).
- **Stepping through moves**: the ◀ ▶ buttons under the board (or the ← → keys) work throughout the puzzle —
  you can go back to the position before the opponent's move and see what happened. Stepping back is animated too: the piece
  glides back to its square, a captured piece reappears, and the sound matches the move being undone (capture,
  check, castling…). You cannot move or see a hint in an earlier position; ▶ to the end (or the opponent's next
  move) returns to the current position.
- **Puzzle modes**: the chip above the puzzle ("Rated ▾") opens the mode picker:
  - *Rated* — the default: puzzles picked for your level and weak spots,
  - *Train a theme* — only puzzles with one theme (forks, pins, mates in 2…), still at your level and still rated;
    each theme shows how many puzzles it has and your success rate in it (weak themes in orange),
  - *Review mistakes* — puzzles you failed come back, oldest first, until you solve them without a mistake or a hint;
    unrated, and when the queue is empty you go back to rated puzzles,
  - *Puzzle Rush* — 3 min, 5 min or Survival (no clock): every puzzle is a little harder (from about 600), a mistake,
    a hint or giving up is a strike, and 3 strikes end the run. Unrated; the best score of each variant is remembered
    and the summary shows the rating of every puzzle in the run.

  Switching modes in the middle of a rated puzzle asks first, because the started puzzle then counts as unsolved.
- **Buttons**: during a puzzle you see "Hint" and "Show solution" (after a mistake also "Try again");
  "Next puzzle" appears only after solving the puzzle or revealing the solution.
- **Alternative solutions**: a move other than the reference move that delivers mate solves the puzzle. A move that,
  according to the engine, is still clearly winning (evaluation > +3 and at most 0.5 pawn worse than the best) gives the message
  "Good move, but there is a better one. Try again" and is not counted as a mistake.
- **The "AI Brain" panel** has three modes:
  - *Hidden* — while solving, only the counters and the fact that the AI is calculating are visible,
  - *Hint* — highlights the piece that has to move (the rating reward is halved),
  - *Full* — after the puzzle (or after a mistake) everything is visible: the evaluation bar, arrows (best move in lime,
    second and third semi-transparent), 3 candidate lines in SAN, the stream of thoughts, the mini tree, and the AI explains the puzzle.
    Clicking a candidate line replays it on the board in preview mode.
- **Rating**: a big number at the top (e.g. "1450 ± 80") with an animated change (+12 in lime, −9 in red),
  a streak with a fire icon, the puzzle rating shown once the puzzle is over, and a "Why this puzzle?" pop-up.
- After a puzzle ends, ◀ ▶ (or ← →) step through the positions, and the engine analyses each of them.
- **Arrows and highlights (like on chess.com)**: drag with the right mouse button from square to square to
  draw an arrow (a knight move is drawn as an L), and click to highlight a square. Shift = red,
  Ctrl = blue, Alt = lime, no modifier = amber. Drawing the same arrow again removes it; a left click
  on the board or making a move clears the drawings.
- **Language**: the interface is in English by default, and Polish is available as a second language. The EN / PL switch in
  the top bar changes the whole interface, including the AI's "thoughts", explanations, theme names and the piece letters in
  notation (Q/R/B/N in English; the Polish locale uses Polish piece letters H/W/G/S). The choice is remembered.
- **Resolution and responsiveness**: the whole interface scales to the window size (from a small window up to 4K), and texts
  fit their boxes (they shrink the font or get truncated with "…" instead of overflowing).
  In a wide window the board has the panel beside it and a vertical evaluation bar; in a narrow one (like a phone) there is a
  two-row top bar, a horizontal evaluation bar above the board, the panel below it, and the whole page scrolls with the mouse wheel.
- **Icon**: the window has its own icon (a white pawn on a tile): `web/public/icon.png`
  (on Linux the window uses its built copy, `tacticmind/web/static/icon.png`). Windows needs a real .ico,
  `web/public/icon.ico`, made from the PNG with `python scripts/make_icon.py`.
- **Sounds (chess.com style)**: a warm wooden "thock" on a move (a piece set down on a wooden board), a sharper
  piece-on-piece click followed by the thock on a capture, a thock with a short marimba note on check, two quick thocks
  on castling, rising marimba notes on promotion and after solving a puzzle (an arpeggio with a bell for a brilliant
  move) and a soft low pair after a mistake. All of them are synthesized in code on Web Audio (`web/src/sound.ts`):
  a short contact pulse rings a bank of resonators tuned like a wooden board, a piece and a marimba bar, so there
  are no recordings under someone else's license.
- **Volume**: the top bar has a volume slider (drag it, click it or scroll the mouse wheel over it);
  the speaker icon mutes/unmutes the sound. The volume is remembered in the profile.
- **Full screen**: F11 or the ⛶ button in the top-right corner toggles full-screen mode of the window.
- **Settings** (gear in the top bar): an FPS counter in the bottom-left corner (F3 toggles it), an animation
  frame limit (60, 120, 144, 170, 240 or unlimited, as fast as the monitor refreshes), a dark or light theme and the
  board colours (green, terracotta or slate).
- **Dragging like on chess.com**: a grabbed piece jumps under the cursor at once and follows it with barely any
  inertia; the cursor is an open hand over a piece you can move and a closed one while you hold it, and the square it
  would land on gets a light frame. Letting go on the same square just selects the piece (click-click); a second click puts
  it down. The coach's pieces can be picked up too; they always go back. **Pre-moves**: while the coach thinks, you can
  queue a move (its squares turn red), also onto your own piece for a recapture; the piece stands on its target at
  once. It is played as soon as it is your turn if it is legal then; otherwise it slides back and the pre-move is
  dropped. A right click or a click on an empty square cancels it.
- **Look and animations**: a "chess club poster" style: a warm dark background with a dot grid (or warm paper in the
  light theme), cards and buttons with thick ink outlines and hard offset shadows, acid lime for the player and hot pink
  for the AI, the Bricolage Grotesque display font for headings, Space Grotesk for text and Space Mono for numbers
  and moves. The board is cream and green, with the pieces Juras drew for the game (traced into SVG from its 4× AI upscale by
  `scripts/trace_pieces.py`: a thin outline, a flat fill and a shaded right edge). A grabbed piece follows the pointer on its own compositor layer, so dragging stays smooth. Animations: smooth piece movement
  (a captured piece disappears), a popping ✓/✗ with a ripple, a board shake after a mistake, confetti after solving,
  a pulsing hint and check, a springy evaluation bar, screen cross-fades, sliding toggle indicators.

## Playing against the coach

The **"Coach"** tab. The coach is called Maks — his portrait (with several facial expressions that change during the game)
is drawn in SVG (`web/src/components/CoachAvatar.tsx`), without image files.

- **Game settings**: the coach's strength set with a slider from 400 to 2900 Elo (with a label: beginner, amateur,
  intermediate, advanced, expert, master and, at the top, full engine strength), colour (white / random / black) and a "Play" button.
- **"Your level"**: the first 10 games are calibration (a "calibration 3/10" counter). After the 10th game
  a new difficulty level unlocks — the coach plays at a strength equal to your game rating. This level
  changes **every 5 games** (after the 15th, 20th, 25th …), and the game summary tells you when the next change will happen.
- **During the game**: after each of your moves the coach shows a move-class badge on the target square and in the move
  list — !! brilliant, ! great, ★ best, ✓ excellent / good, book (from theory), ?! inaccuracy,
  ? mistake, ?? blunder — and says what the move does, or what the opponent threatens and what was better, e.g.
  "The opponent will reply 1... hxg6 and you lose your queen. Nc3 was better — it develops the knight.".
  After a **mistake or blunder** the game pauses: "Take back and fix" (an arrow shows the better move)
  or "Keep playing". The coach also comments on its own moves and warns about its threats ("Careful — I'm threatening mate!").
  The coach's face reacts to your moves (joy, worry, surprise), and while calculating it looks thoughtful.
- **Help**: "Hint" (an arrow for the best move) and "Take back move". Each use of help lowers the game result
  counted towards "Your level" by 0.1.
- **Opening name** shown live (e.g. "Sicilian Defence — Najdorf Variation"), recognized from the position, so
  it also works with transpositions.
- **Player bars** above and below the board: the coach's portrait and your icon, whose turn it is, captured pieces
  (the same kind overlapping a little, like on chess.com) and material advantage.
- **Evaluation bar** beside the board: the engine's evaluation of the position on the board (also when stepping
  through the game); under the pointer the exact value (e.g. +0.37) shows at the border between white and black, like
  on chess.com. The button with the bar icon under the board shows or hides it; the choice is remembered. The bar and
  the move classes come from an analysis as deep as its time allows (about depth 15–20 in 1.6 s with the C engine).
- **After the game**: a summary with your and the coach's **accuracy** (%), the number of moves in each class and the level change.
  With the ◀ ▶ buttons (or by clicking a move in the list) you review the game — each move brings back the coach's comment,
  and for weaker moves an arrow shows what was better. "Rematch" starts a new game with the same settings.
- **Advantage graph and PGN**: after the game an "Advantage" graph shows White's winning chance after every move
  (as in chess.com's Game Review), with dots on your inaccuracies, mistakes, blunders and great or brilliant moves; clicking
  or dragging on the graph jumps to that move. "Copy PGN" and "Save PGN" export the game with the move classes as
  annotation symbols (!!, !, ?!, ?, ??), the engine evaluation (`[%eval]`, read by Lichess and chess.com) and the coach's
  comments; the file goes to the Downloads folder. The graph uses the analyses the coach already made during the game, so it costs no extra engine time.
- **Your games**: the "Your games" tab on the coach screen lists your recent games (result, coach strength, opening,
  accuracy, rating change). Clicking one opens it in the same review — board, badges, the coach's comments in the current
  language, the graph and PGN. The newest 100 games keep their moves in the profile (`coach/archive.py`); games saved
  before this feature only have their result.
- **Opening lessons**: 15 openings — for White the Italian Game, Ruy Lopez, Scotch Game, Queen's Gambit, London System,
  English Opening; for Black the Sicilian Defence (Najdorf), French, Caro-Kann, Scandinavian, Two
  Knights, Slav, King's Indian, Nimzo-Indian and Grünfeld. You play the main-line moves, the coach replies
  with moves from that line and **explains every move** (both sides). A move off the line is taken back, and the coach says
  what is played here and why (if your move is also theory, it says so too). Completing an opening earns stars: 1 —
  completed, 2 — without a mistake, 3 — three times without a mistake. After the lesson you can keep playing from that
  position — it then becomes a regular game, counted towards "Your level".
- On the coach screens the top bar shows your coach-game rating (separate from the puzzle rating).
