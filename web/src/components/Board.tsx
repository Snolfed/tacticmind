// Chessboard: squares and arrows in SVG (sharp at any zoom), pieces as SVG images.
// Python provides the position and what is legal; here we handle animations, dragging, promotion choice
// and drawing arrows with the right mouse button.

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactElement } from "react";
import { store } from "../api";
import {
  applyMove,
  arrowPath,
  arrowPoints,
  easeInOutCubic,
  easeOutCubic,
  fromView,
  parseFen,
  splitAlpha,
  squareIndex,
  squareName,
  toView,
  transition,
  type Placement,
  type Transition,
} from "../chess";
import { ACCENT, BRILLIANT, CONFETTI, WHITE, effects } from "../effects";
import { useFrame } from "../ticker";
import type { BoardSnapshot, Color } from "../types";
import { BADGE_COLORS, Badge } from "./Badge";

/** Move animation duration. */
const MOVE_TIME = 200;
/** How quickly a dragged piece catches up with the cursor (time constant, ms): barely any inertia, like on chess.com. */
const DRAG_FOLLOW = 12;
const PROMOTION_PIECES = ["q", "n", "r", "b"];
const USER_COLORS = {
  plain: "rgba(251,191,36,0.8)",
  shift: "rgba(255,81,72,0.8)",
  ctrl: "rgba(96,165,250,0.8)",
  alt: "rgba(198,241,53,0.8)",
};

export function pieceUrl(piece: string): string {
  return `/pieces/${piece}.svg`;
}

/** Target squares of each piece's moves (UCI list → from → set of to). */
function targetsOf(moves: string[]): Map<number, Set<number>> {
  const targets = new Map<number, Set<number>>();
  for (const uci of moves) {
    const from = squareIndex(uci.slice(0, 2));
    const set = targets.get(from) ?? new Set<number>();
    set.add(squareIndex(uci.slice(2, 4)));
    targets.set(from, set);
  }
  return targets;
}

function signature(placement: Placement): string {
  let sig = "";
  for (let square = 0; square < 64; square++) sig += placement.get(square) ?? "--";
  return sig;
}

function rgbOf(css: string): [number, number, number] {
  const match = /(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(css);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : [142, 150, 175];
}

interface Anim extends Transition {
  start: number;
}

interface View {
  sig: string;
  placement: Placement;
  orientation: Color;
  seq: number;
  anim: Anim | null;
}

interface Optimistic {
  seq: number;
  uci: string;
  animate: boolean;
}

interface DragInfo {
  from: number;
  x: number;
  y: number;
  lastX: number;
  lastY: number;
  moved: boolean;
  /** The piece was already selected when it was grabbed: letting go without moving it unselects it. */
  wasSelected: boolean;
  /** Board position on screen, measured once when the piece is grabbed (no layout reads while dragging). */
  left: number;
  top: number;
  size: number;
  /** Where the dragged piece is drawn (relative to the board): it chases the cursor. */
  gx: number;
  gy: number;
}

export interface BoardProps {
  board: BoardSnapshot;
  /** Board name in "fx" events from the server (play / coach). */
  name?: string;
  onMove?: (uci: string) => void;
  /** Arrows pulse (the decorative board on the home page). */
  pulseArrows?: boolean;
  className?: string;
}

export function Board({ board, name, onMove, pulseArrows = false, className }: BoardProps): ReactElement {
  const wrap = useRef<HTMLDivElement>(null);
  const pieceEls = useRef(new Map<number, HTMLElement>());
  const ghostEls = useRef(new Map<number, HTMLElement>());
  const dragEl = useRef<HTMLImageElement>(null);
  const dragInfo = useRef<DragInfo | null>(null);
  const [, setTick] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [promotion, setPromotion] = useState<{ from: number; to: number; animate: boolean } | null>(null);
  const [optimistic, setOptimistic] = useState<Optimistic | null>(null);
  const [userArrows, setUserArrows] = useState<Map<string, string>>(new Map());
  const [marks, setMarks] = useState<Map<number, string>>(new Map());
  const [drawing, setDrawing] = useState<{ from: number; to: number; color: string } | null>(null);
  /** The square under a dragged piece (framed when the piece may land there). */
  const [hover, setHover] = useState<number | null>(null);
  /** The pointer is over a piece the player can pick up (an open-hand cursor). */
  const [overPiece, setOverPiece] = useState(false);
  /** A move queued while the opponent thinks (pre-move). */
  const [premove, setPremove] = useState<{ from: number; to: number } | null>(null);

  const orientation = board.orientation;
  const serverPlacement = useMemo(() => parseFen(board.fen), [board.fen]);
  const pending = optimistic && optimistic.seq === board.seq ? optimistic : null;
  const placement = useMemo(() => (pending ? applyMove(serverPlacement, pending.uci) : serverPlacement), [serverPlacement, pending]);
  const sig = useMemo(() => signature(placement), [placement]);

  // --- animation: compare the new position with the one on screen (idempotent computation, no side effects)
  const view = useRef<View>({ sig: "", placement, orientation, seq: board.seq, anim: null });
  const v = view.current;
  if (v.sig !== sig || v.orientation !== orientation) {
    const animate = v.sig !== "" && v.orientation === orientation && (pending ? pending.animate : board.anim !== "none" && board.seq !== v.seq);
    v.anim = animate ? { start: performance.now(), ...transition(v.placement, placement) } : null;
    v.sig = sig;
    v.placement = placement;
    v.orientation = orientation;
    v.seq = board.seq;
  }
  const anim = v.anim;

  const legal = useMemo(() => targetsOf(board.legal), [board.legal]);
  const premoveTargets = useMemo(() => targetsOf(board.premoves), [board.premoves]);
  const canMove = board.interactive && !pending && !!onMove;
  // While the opponent thinks, a move can be queued (a pre-move) and is played as soon as it is the player's turn.
  const canPremove = !canMove && board.premoves.length > 0 && !!onMove;
  // Any piece can be picked up, like on chess.com; the opponent's ones always go back to their square.
  const canPick = canMove || canPremove;
  const playerPrefix = board.player === "white" ? "w" : "b";

  // The server's reply (a new position number) ends the "tentative move", the selection and the drawings.
  useEffect(() => {
    setOptimistic(null);
    setSelected(null);
    setPromotion(null);
    setUserArrows(new Map());
    setMarks(new Map());
  }, [board.seq]);

  // Move rejected (e.g. the position changed in the meantime) — after a moment the piece returns to its square.
  useEffect(() => {
    if (!optimistic) return;
    const timer = window.setTimeout(() => setOptimistic((current) => (current === optimistic ? null : current)), 1500);
    return () => window.clearTimeout(timer);
  }, [optimistic]);

  useEffect(() => {
    if (!canMove) {
      setSelected(null);
      setPromotion(null);
    }
  }, [canMove]);

  // The player's turn has come: the pre-move is played at once if it is legal now (a promotion becomes a queen),
  // otherwise it is dropped. A take-back or the end of the game drops it too.
  useEffect(() => {
    if (!premove) return;
    if (board.anim === "undo" || (!canMove && !canPremove)) {
      setPremove(null);
      return;
    }
    if (!canMove) return;
    const prefix = squareName(premove.from) + squareName(premove.to);
    const moves = board.legal.filter((uci) => uci.startsWith(prefix));
    setPremove(null);
    if (moves.length) commit(moves.find((uci) => uci.endsWith("q")) ?? (moves[0] as string), true);
  }, [canMove, canPremove, board.seq]);

  // --- piece animation in the frame loop (with the FPS limit from the settings)
  const progress = (now: number): number => (anim ? Math.min(1, (now - anim.start) / MOVE_TIME) : 1);
  useFrame((now) => {
    const current = view.current.anim;
    if (!current) return;
    const t = Math.min(1, (now - current.start) / MOVE_TIME);
    if (t >= 1) {
      view.current.anim = null;
      setTick((n) => n + 1);
      return;
    }
    const p = easeInOutCubic(t);
    for (const motion of current.moves) {
      const el = pieceEls.current.get(motion.to);
      if (el) el.style.transform = offset(motion.from, motion.to, p);
    }
    const fade = easeOutCubic(t * 1.4);
    for (const { square } of current.vanish) {
      const el = ghostEls.current.get(square);
      if (el) el.style.opacity = String(1 - fade);
    }
    for (const { square } of current.appear) {
      const el = pieceEls.current.get(square);
      if (el) el.style.opacity = String(fade);
    }
  }, anim !== null);

  function offset(from: number, to: number, p: number): string {
    const [fc, fr] = toView(from, orientation);
    const [tc, tr] = toView(to, orientation);
    return `translate(${((fc - tc) * (1 - p) * 100).toFixed(2)}%, ${((fr - tr) * (1 - p) * 100).toFixed(2)}%)`;
  }

  // --- effects: badge on a square (ring, sparks), shake, confetti
  const lastFeedback = useRef(board.feedback?.seq ?? 0);
  useEffect(() => {
    const feedback = board.feedback;
    if (!feedback || feedback.seq === lastFeedback.current) return;
    lastFeedback.current = feedback.seq;
    if (!feedback.effect || !wrap.current) return;
    const rect = wrap.current.getBoundingClientRect();
    const s = rect.width / 8;
    const [col, row] = toView(squareIndex(feedback.square), orientation);
    const x = rect.left + (col + 0.9) * s;
    const y = rect.top + (row + 0.1) * s;
    const kind = feedback.kind.startsWith("cls:") ? feedback.kind.slice(4) : feedback.kind;
    effects.ring(x, y, s * 0.3, rgbOf(BADGE_COLORS[kind] ?? "rgb(198,241,53)"));
    if (kind === "brilliant") {
      effects.ring(x, y, s * 0.55, BRILLIANT, 0.9);
      effects.burst(x, y, [BRILLIANT, WHITE, ACCENT], 22, Math.min(1.6, Math.max(0.6, s / 80)));
    }
  }, [board.feedback, orientation]);

  useEffect(() => {
    if (!name) return;
    return store.onFx((event) => {
      const el = wrap.current;
      if (!el || !("board" in event) || event.board !== name) return;
      if (event.type === "shake") {
        const frames: Keyframe[] = [];
        for (let i = 0; i <= 24; i++) {
          const t = (i / 24) * 0.4;
          frames.push({ transform: `translateX(${(Math.sin(t * 48) * 9 * (1 - t / 0.4)).toFixed(2)}px)` });
        }
        el.animate(frames, { duration: 400 });
      } else if (event.type === "celebrate") {
        const rect = el.getBoundingClientRect();
        const s = rect.width / 8;
        const [col, row] = toView(squareIndex(event.square), orientation);
        effects.burst(rect.left + (col + 0.5) * s, rect.top + (row + 0.5) * s, CONFETTI, 46, Math.min(1.6, Math.max(0.6, s / 80)));
      }
    });
  }, [name, orientation]);

  // --- pointer: click, drag, right-button arrows
  function squareAt(clientX: number, clientY: number): number {
    const el = wrap.current;
    if (!el) return -1;
    const rect = el.getBoundingClientRect();
    const col = Math.floor(((clientX - rect.left) / rect.width) * 8);
    const row = Math.floor(((clientY - rect.top) / rect.height) * 8);
    if (col < 0 || col > 7 || row < 0 || row > 7) return -1;
    return fromView(col, row, orientation);
  }

  function commit(uci: string, animate: boolean): void {
    setSelected(null);
    setPromotion(null);
    setOptimistic({ seq: board.seq, uci, animate });
    onMove?.(uci);
  }

  function attempt(from: number, to: number, animate: boolean): void {
    const prefix = squareName(from) + squareName(to);
    const moves = board.legal.filter((uci) => uci.startsWith(prefix));
    setSelected(null);
    if (!moves.length) return;
    if (moves.some((uci) => uci.length === 5)) {
      setPromotion({ from, to, animate });
      return;
    }
    commit(moves[0] as string, animate);
  }

  function placeGhost(): void {
    const ghost = dragEl.current;
    const info = dragInfo.current;
    if (!ghost || !info) return;
    ghost.style.transform = `translate3d(${info.gx.toFixed(1)}px, ${info.gy.toFixed(1)}px, 0) translate(-50%, -50%)`;
  }

  // A grabbed piece jumps to the cursor at once (like on chess.com), before the next mouse move arrives.
  useLayoutEffect(() => {
    if (dragFrom !== null) placeGhost();
  }, [dragFrom]);

  // ... and then follows it: each frame it covers most of the remaining way.
  useFrame((_now, dt) => {
    const info = dragInfo.current;
    if (!info) return;
    const pull = 1 - Math.exp((-dt * 1000) / DRAG_FOLLOW);
    info.gx += (info.lastX - info.left - info.gx) * pull;
    info.gy += (info.lastY - info.top - info.gy) * pull;
    placeGhost();
  }, dragFrom !== null);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    const square = squareAt(event.clientX, event.clientY);
    if (event.button === 2) {
      setSelected(null);
      setPromotion(null);
      if (premove) {
        setPremove(null); // a right click cancels the pre-move, like on chess.com
        return;
      }
      if (square < 0) return;
      const color = event.shiftKey ? USER_COLORS.shift : event.ctrlKey ? USER_COLORS.ctrl : event.altKey ? USER_COLORS.alt : USER_COLORS.plain;
      setDrawing({ from: square, to: square, color });
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0) return;
    if (promotion) {
      setPromotion(null);
      return;
    }
    if (square < 0) {
      setSelected(null);
      return;
    }
    if (userArrows.size || marks.size) {
      setUserArrows(new Map());
      setMarks(new Map());
    }
    if (selected !== null && canMove && legal.get(selected)?.has(square)) {
      attempt(selected, square, true);
      return;
    }
    if (selected !== null && canPremove && premoveTargets.get(selected)?.has(square)) {
      setPremove({ from: selected, to: square });
      setSelected(null);
      return;
    }
    const piece = placement.get(square);
    if (premove && !piece) setPremove(null); // a click on an empty square cancels the pre-move
    if (canPick && piece) {
      setSelected(square);
      const rect = event.currentTarget.getBoundingClientRect();
      dragInfo.current = {
        from: square,
        x: event.clientX,
        y: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        moved: false,
        wasSelected: selected === square,
        left: rect.left,
        top: rect.top,
        size: rect.width / 8,
        gx: event.clientX - rect.left,
        gy: event.clientY - rect.top,
      };
      setDragFrom(square);
      event.currentTarget.setPointerCapture(event.pointerId);
    } else {
      setSelected(null);
    }
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    if (drawing) {
      const square = squareAt(event.clientX, event.clientY);
      if (square >= 0 && square !== drawing.to) setDrawing({ ...drawing, to: square });
      return;
    }
    const info = dragInfo.current;
    if (!info) {
      const square = squareAt(event.clientX, event.clientY);
      const pickable = canPick && square >= 0 && placement.has(square);
      if (pickable !== overPiece) setOverPiece(pickable);
      return;
    }
    info.lastX = event.clientX;
    info.lastY = event.clientY;
    if (!info.moved && Math.hypot(event.clientX - info.x, event.clientY - info.y) > Math.max(6, info.size * 0.12)) info.moved = true;
    const col = Math.floor((event.clientX - info.left) / info.size);
    const row = Math.floor((event.clientY - info.top) / info.size);
    const square = col >= 0 && col < 8 && row >= 0 && row < 8 ? fromView(col, row, orientation) : null;
    if (square !== hover) setHover(square);
  }

  function onPointerUp(event: ReactPointerEvent<HTMLDivElement>): void {
    if (drawing && event.button === 2) {
      const end = squareAt(event.clientX, event.clientY);
      setDrawing(null);
      if (end < 0) return;
      if (end === drawing.from) {
        const next = new Map(marks);
        if (next.get(end) === drawing.color) next.delete(end);
        else next.set(end, drawing.color);
        setMarks(next);
      } else {
        const key = `${drawing.from}-${end}`;
        const next = new Map(userArrows);
        if (next.get(key) === drawing.color) next.delete(key);
        else next.set(key, drawing.color);
        setUserArrows(next);
      }
      return;
    }
    const info = dragInfo.current;
    if (!info || event.button !== 0) return;
    dragInfo.current = null;
    setDragFrom(null);
    setHover(null);
    const target = squareAt(event.clientX, event.clientY);
    if (target === info.from) {
      if (info.wasSelected && !info.moved) setSelected(null); // a second click on the selected piece puts it down
    } else if (target >= 0 && legal.get(info.from)?.has(target)) {
      attempt(info.from, target, false); // the piece is already in place — no animation
    } else if (target >= 0 && canPremove && premoveTargets.get(info.from)?.has(target)) {
      setPremove({ from: info.from, to: target });
      setSelected(null);
    } else {
      setSelected(null); // dropped on an illegal square — it returns to its place
    }
  }

  function onPointerCancel(): void {
    dragInfo.current = null;
    setDragFrom(null);
    setHover(null);
    setDrawing(null);
  }

  // While a piece is held the cursor is an open hand everywhere, also outside the board.
  useEffect(() => {
    if (dragFrom === null) return;
    document.documentElement.classList.add("holding-piece");
    return () => document.documentElement.classList.remove("holding-piece");
  }, [dragFrom]);

  // --- drawing
  const lastMove = board.lastMove;
  const nowP = easeInOutCubic(progress(performance.now()));
  const motionTo = new Map(anim?.moves.map((m) => [m.to, m]) ?? []);
  const appearing = new Set(anim?.appear.map((a) => a.square) ?? []);
  const fadeNow = anim ? easeOutCubic(progress(performance.now()) * 1.4) : 1;

  const squareRect = (square: number): { x: number; y: number } => {
    const [col, row] = toView(square, orientation);
    return { x: col, y: row };
  };

  const squares: ReactElement[] = [];
  for (let square = 0; square < 64; square++) {
    const { x, y } = squareRect(square);
    const light = ((square % 8) + Math.floor(square / 8)) % 2 === 1;
    squares.push(<rect key={square} x={x} y={y} width={1} height={1} className={light ? "sq-light" : "sq-dark"} />);
  }
  const coords: ReactElement[] = [];
  for (let i = 0; i < 8; i++) {
    const fileSquare = orientation === "white" ? i : 56 + i; // bottom rank
    const rankSquare = orientation === "white" ? i * 8 : i * 8 + 7; // left file
    const f = squareRect(fileSquare);
    const r = squareRect(rankSquare);
    const fileLight = ((fileSquare % 8) + Math.floor(fileSquare / 8)) % 2 === 1;
    const rankLight = ((rankSquare % 8) + Math.floor(rankSquare / 8)) % 2 === 1;
    coords.push(
      <text key={`f${i}`} x={(f.x + 0.95) * 100} y={(f.y + 0.95) * 100} textAnchor="end" className={fileLight ? "coord-on-light" : "coord-on-dark"}>
        {"abcdefgh"[i]}
      </text>,
      <text key={`r${i}`} x={(r.x + 0.05) * 100} y={(r.y + 0.2) * 100} className={rankLight ? "coord-on-light" : "coord-on-dark"}>
        {i + 1}
      </text>,
    );
  }

  const tints: ReactElement[] = [];
  if (lastMove) {
    for (const name of [lastMove.slice(0, 2), lastMove.slice(2, 4)]) {
      const { x, y } = squareRect(squareIndex(name));
      tints.push(<rect key={`lm-${name}`} x={x} y={y} width={1} height={1} className="sq-last" />);
    }
  }
  if (premove) {
    for (const square of [premove.from, premove.to]) {
      const { x, y } = squareRect(square);
      tints.push(<rect key={`pre-${square}`} x={x} y={y} width={1} height={1} className="sq-premove" />);
    }
  }
  if (selected !== null) {
    const { x, y } = squareRect(selected);
    tints.push(<rect key="sel" x={x} y={y} width={1} height={1} className="sq-selected" />);
  }
  for (const [square, color] of marks) {
    const { x, y } = squareRect(square);
    const [rgb] = splitAlpha(color);
    tints.push(
      <rect key={`mark-${square}`} x={x + 0.05} y={y + 0.05} width={0.9} height={0.9} rx={0.1} fill={rgb} fillOpacity={0.47} stroke={rgb} strokeOpacity={0.9} strokeWidth={0.04} />,
    );
  }
  const glows: ReactElement[] = [];
  if (board.check) {
    const { x, y } = squareRect(squareIndex(board.check));
    glows.push(<circle key="check" cx={x + 0.5} cy={y + 0.5} r={0.78} fill="url(#check-glow)" className="glow-check" />);
  }
  if (board.hint) {
    const { x, y } = squareRect(squareIndex(board.hint));
    glows.push(
      <g key={`hint-${board.hint}`} className="glow-hint">
        <circle cx={x + 0.5} cy={y + 0.5} r={0.75} fill="url(#hint-glow)" />
        <circle cx={x + 0.5} cy={y + 0.5} r={0.45} fill="none" stroke="rgba(255,106,168,0.9)" strokeWidth={0.05} />
      </g>,
    );
  }

  // Legal moves of the selected piece: dots pop up and capture rings close in, in a wave from the piece outwards.
  // HTML rather than SVG: scaling SVG shapes left stray lines in WebKitGTK (the fallback game window on Linux).
  const dots: ReactElement[] = [];
  // Only the player's own pieces show where they can go (the opponent's are picked up just to hold them).
  const targets = selected === null ? undefined : canMove ? legal.get(selected) : canPremove ? premoveTargets.get(selected) : undefined;
  if (selected !== null && targets) {
    const from = squareRect(selected);
    for (const target of targets) {
      const { x, y } = squareRect(target);
      const delay = Math.min(110, Math.hypot(x - from.x, y - from.y) * 16);
      const kind = placement.has(target) ? "hint-capture" : "hint-dot";
      dots.push(<div key={`${selected}-${target}`} className={`hint ${kind}`} style={{ left: `${x * 12.5}%`, top: `${y * 12.5}%`, animationDelay: `${delay.toFixed(0)}ms` }} />);
    }
    if (dragFrom !== null && hover !== null && hover !== selected && targets.has(hover)) {
      const { x, y } = squareRect(hover);
      dots.push(<div key="drop" className="hint hint-drop" style={{ left: `${x * 12.5}%`, top: `${y * 12.5}%` }} />);
    }
  }

  const arrowEls: ReactElement[] = [];
  const engineArrows = [...board.arrows].reverse(); // the best move is drawn on top
  engineArrows.forEach(([from, to, color], i) => {
    const [rgb, alpha] = splitAlpha(color);
    const width = i === engineArrows.length - 1 ? 0.2 : 0.16;
    const d = arrowPath(arrowPoints(squareIndex(from), squareIndex(to), orientation), width);
    arrowEls.push(<path key={`e-${from}${to}`} d={d} fill={rgb} opacity={alpha} className={pulseArrows ? "arrow arrow-pulse" : "arrow"} />);
  });
  for (const [key, color] of userArrows) {
    const [from, to] = key.split("-").map(Number) as [number, number];
    const [rgb, alpha] = splitAlpha(color);
    arrowEls.push(<path key={`u-${key}`} d={arrowPath(arrowPoints(from, to, orientation), 0.18)} fill={rgb} opacity={alpha} />);
  }
  if (drawing && drawing.to !== drawing.from) {
    const [rgb] = splitAlpha(drawing.color);
    arrowEls.push(<path key="drawing" d={arrowPath(arrowPoints(drawing.from, drawing.to, orientation), 0.18)} fill={rgb} opacity={0.55} />);
  }

  const pieceStyle = (square: number): CSSProperties => {
    const { x, y } = squareRect(square);
    return { left: `${x * 12.5}%`, top: `${y * 12.5}%` };
  };

  const pieces: ReactElement[] = [];
  for (const { piece, square } of anim?.vanish ?? []) {
    pieces.push(
      <img
        key={`ghost-${square}`}
        ref={(el) => {
          if (!el) return;
          ghostEls.current.set(square, el);
          return () => {
            if (ghostEls.current.get(square) === el) ghostEls.current.delete(square);
          };
        }}
        className="piece"
        src={pieceUrl(piece)}
        alt=""
        draggable={false}
        style={{ ...pieceStyle(square), opacity: 1 - fadeNow }}
      />,
    );
  }
  for (const [square, piece] of placement) {
    const motion = motionTo.get(square);
    const style: CSSProperties = pieceStyle(square);
    if (motion) style.transform = offset(motion.from, motion.to, nowP);
    if (appearing.has(square)) style.opacity = fadeNow;
    if (dragFrom === square) style.visibility = "hidden";
    pieces.push(
      <img
        key={`p-${square}-${piece}`}
        ref={(el) => {
          if (!el) return;
          pieceEls.current.set(square, el);
          return () => {
            if (pieceEls.current.get(square) === el) pieceEls.current.delete(square);
          };
        }}
        className="piece"
        src={pieceUrl(piece)}
        alt=""
        draggable={false}
        style={style}
      />,
    );
  }

  let badge: ReactElement | null = null;
  if (board.feedback) {
    const feedback = board.feedback;
    const { x, y } = squareRect(squareIndex(feedback.square));
    const kind = feedback.kind.startsWith("cls:") ? feedback.kind.slice(4) : feedback.kind;
    badge = (
      <div
        key={`badge-${feedback.seq}`}
        className={`board-badge${feedback.effect ? " pop" : ""}${kind === "brilliant" ? " brilliant" : ""}`}
        style={{ left: `${(x + 0.9) * 12.5}%`, top: `${(y + 0.1) * 12.5}%` }}
      >
        <Badge kind={kind} size={64} />
      </div>
    );
  }

  let chooser: ReactElement | null = null;
  if (promotion) {
    const { x, y } = squareRect(promotion.to);
    const down = y < 4;
    const color = placement.get(promotion.from)?.[0] ?? playerPrefix;
    chooser = (
      <div className="promotion" style={{ left: `${x * 12.5}%`, top: `${(down ? y : y - 3) * 12.5}%` }} onPointerDown={(e) => e.stopPropagation()}>
        {(down ? PROMOTION_PIECES : [...PROMOTION_PIECES].reverse()).map((letter) => (
          <button
            key={letter}
            type="button"
            className="promotion-option"
            onClick={() => commit(squareName(promotion.from) + squareName(promotion.to) + letter, promotion.animate)}
          >
            <img src={pieceUrl(color + letter.toUpperCase())} alt={letter} draggable={false} />
          </button>
        ))}
      </div>
    );
  }

  // The dragged piece is rendered (hidden) as soon as a piece is picked, so its image is ready before the drag starts.
  const liftFrom = dragFrom ?? (canMove ? selected : null);
  const dragPiece = liftFrom !== null ? placement.get(liftFrom) : undefined;

  return (
    <div
      ref={wrap}
      className={`board${canMove ? " can-move" : ""}${overPiece ? " over-piece" : ""}${dragFrom !== null ? " dragging" : ""}${className ? " " + className : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onPointerLeave={() => setOverPiece(false)}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="board-clip">
        <svg className="board-layer" viewBox="0 0 8 8" shapeRendering="crispEdges">
          {squares}
        </svg>
        {/* Coordinates in a separate, larger-scale layer — browsers render very small fonts in SVG poorly. */}
        <svg className="board-layer" viewBox="0 0 800 800">
          {coords}
        </svg>
        <svg className="board-layer" viewBox="0 0 8 8">
          <defs>
            <radialGradient id="check-glow">
              <stop offset="0" stopColor="rgb(255,81,72)" stopOpacity={0.95} />
              <stop offset="0.45" stopColor="rgb(255,81,72)" stopOpacity={0.6} />
              <stop offset="1" stopColor="rgb(255,81,72)" stopOpacity={0} />
            </radialGradient>
            <radialGradient id="hint-glow">
              <stop offset="0.35" stopColor="rgb(255,106,168)" stopOpacity={0.55} />
              <stop offset="1" stopColor="rgb(255,106,168)" stopOpacity={0} />
            </radialGradient>
          </defs>
          {tints}
          {glows}
        </svg>
        <div className="pieces">{pieces}</div>
        <div className="hints">{dots}</div>
        <svg className="board-layer" viewBox="0 0 8 8">
          {arrowEls}
        </svg>
        {promotion && <div className="promotion-shade" />}
      </div>
      {badge}
      {chooser}
      {dragPiece && <img ref={dragEl} className={`drag-piece${dragFrom !== null ? " lifted" : ""}`} src={pieceUrl(dragPiece)} alt="" draggable={false} />}
    </div>
  );
}
