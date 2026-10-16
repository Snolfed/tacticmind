// Małe, czyste funkcje szachowe potrzebne interfejsowi: FEN → rozstawienie, pola, animacja ruchu,
// geometria strzałek. Zasady gry (legalność ruchów) zna Python — tu tylko rysujemy.

export type Piece = string; // "wK", "bP" …
export type Placement = Map<number, Piece>; // pole (0 = a1 … 63 = h8) → figura

export const FILES = "abcdefgh";

export function squareIndex(name: string): number {
  const file = FILES.indexOf(name[0] ?? "");
  const rank = Number(name[1]) - 1;
  return file < 0 || !(rank >= 0 && rank < 8) ? -1 : rank * 8 + file;
}

export function squareName(index: number): string {
  return (FILES[index % 8] ?? "a") + String(Math.floor(index / 8) + 1);
}

export function parseFen(fen: string): Placement {
  const placement: Placement = new Map();
  const rows = (fen.split(" ")[0] ?? "").split("/");
  rows.forEach((row, i) => {
    const rank = 7 - i;
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) {
        file += Number(ch);
      } else {
        const color = ch === ch.toUpperCase() ? "w" : "b";
        placement.set(rank * 8 + file, color + ch.toUpperCase());
        file += 1;
      }
    }
  });
  return placement;
}

export function turnOf(fen: string): "white" | "black" {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

/** Kolumna i wiersz pola na ekranie (0..7) przy danym obrocie szachownicy. */
export function toView(square: number, orientation: "white" | "black"): [number, number] {
  const file = square % 8;
  const rank = Math.floor(square / 8);
  return orientation === "white" ? [file, 7 - rank] : [7 - file, rank];
}

export function fromView(col: number, row: number, orientation: "white" | "black"): number {
  const file = orientation === "white" ? col : 7 - col;
  const rank = orientation === "white" ? 7 - row : row;
  return rank * 8 + file;
}

/** Ruch gracza zastosowany od razu na ekranie (zanim serwer potwierdzi): roszada, bicie w przelocie, promocja. */
export function applyMove(placement: Placement, uci: string): Placement {
  const next = new Map(placement);
  const from = squareIndex(uci.slice(0, 2));
  const to = squareIndex(uci.slice(2, 4));
  const piece = next.get(from);
  if (!piece) return next;
  next.delete(from);
  if (piece[1] === "P" && from % 8 !== to % 8 && !placement.has(to)) {
    next.delete(to + (piece[0] === "w" ? -8 : 8)); // bicie w przelocie
  }
  if (piece[1] === "K" && Math.abs((to % 8) - (from % 8)) === 2) {
    const rank = Math.floor(from / 8) * 8;
    const kingside = to % 8 === 6;
    const rook = next.get(rank + (kingside ? 7 : 0));
    if (rook) {
      next.delete(rank + (kingside ? 7 : 0));
      next.set(rank + (kingside ? 5 : 3), rook);
    }
  }
  const promotion = uci[4];
  next.set(to, promotion ? piece[0] + promotion.toUpperCase() : piece);
  return next;
}

export interface Motion {
  piece: Piece;
  from: number;
  to: number;
}

export interface Transition {
  /** Figury, które się przesuwają. */
  moves: Motion[];
  /** Figury, które znikają (bite) — przenikanie do zera. */
  vanish: { piece: Piece; square: number }[];
  /** Figury, które się pojawiają (np. zbita figura przy cofaniu ruchu). */
  appear: { piece: Piece; square: number }[];
}

function distance(a: number, b: number): number {
  return Math.hypot((a % 8) - (b % 8), Math.floor(a / 8) - Math.floor(b / 8));
}

/**
 * Animacja między dwiema pozycjami: dopasowujemy figury, które zniknęły z jednych pól,
 * do figur, które pojawiły się na innych (ta sama figura, najbliższe pole). Działa tak samo
 * dla ruchu, cofnięcia, roszady, bicia w przelocie i promocji (pion „zamienia się” w figurę).
 */
export function transition(before: Placement, after: Placement): Transition {
  const appeared: number[] = [];
  const vanished: number[] = [];
  for (let square = 0; square < 64; square++) {
    const a = before.get(square);
    const b = after.get(square);
    if (a === b) continue;
    if (b) appeared.push(square);
    if (a) vanished.push(square);
  }
  const moves: Motion[] = [];
  const used = new Set<number>();
  const unmatched: number[] = [];
  const match = (square: number, same: (piece: Piece, candidate: Piece) => boolean): boolean => {
    const piece = after.get(square) as Piece;
    let best = -1;
    for (const source of vanished) {
      const candidate = before.get(source) as Piece;
      if (used.has(source) || !same(piece, candidate)) continue;
      if (best < 0 || distance(source, square) < distance(best, square)) best = source;
    }
    if (best < 0) return false;
    used.add(best);
    moves.push({ piece: before.get(best) as Piece, from: best, to: square });
    return true;
  };
  for (const square of appeared) if (!match(square, (p, c) => p === c)) unmatched.push(square);
  const appear: { piece: Piece; square: number }[] = [];
  for (const square of unmatched) {
    // Promocja (i jej cofnięcie): ta sama strona, inna figura.
    if (!match(square, (p, c) => p[0] === c[0] && (p[1] === "P" || c[1] === "P"))) appear.push({ piece: after.get(square) as Piece, square });
  }
  const vanish = vanished.filter((square) => !used.has(square)).map((square) => ({ piece: before.get(square) as Piece, square }));
  return { moves, vanish, appear };
}

export function isKnightJump(a: number, b: number): boolean {
  const df = Math.abs((a % 8) - (b % 8));
  const dr = Math.abs(Math.floor(a / 8) - Math.floor(b / 8));
  return (df === 1 && dr === 2) || (df === 2 && dr === 1);
}

/** Punkty strzałki w jednostkach pól (środek pola = x + 0.5); ruch skoczka jako litera L. */
export function arrowPoints(from: number, to: number, orientation: "white" | "black"): [number, number][] {
  const [ac, ar] = toView(from, orientation);
  const [bc, br] = toView(to, orientation);
  const a: [number, number] = [ac + 0.5, ar + 0.5];
  const b: [number, number] = [bc + 0.5, br + 0.5];
  if (isKnightJump(from, to)) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const corner: [number, number] = Math.abs(dx) > Math.abs(dy) ? [b[0], a[1]] : [a[0], b[1]];
    const angle = Math.atan2(b[1] - corner[1], b[0] - corner[0]);
    return [a, corner, [b[0] - Math.cos(angle) * 0.18, b[1] - Math.sin(angle) * 0.18]];
  }
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  return [
    [a[0] + Math.cos(angle) * 0.12, a[1] + Math.sin(angle) * 0.12],
    [b[0] - Math.cos(angle) * 0.18, b[1] - Math.sin(angle) * 0.18],
  ];
}

/** Ścieżka SVG strzałki (trzon + grot) jako jeden wielokąt — półprzezroczysta strzałka nie ma ciemniejszych nakładek. */
export function arrowPath(points: [number, number][], width: number): string {
  const head = width * 2.2;
  const headWidth = width * 2.4;
  const last = points[points.length - 1] as [number, number];
  const prev = points[points.length - 2] as [number, number];
  const angle = Math.atan2(last[1] - prev[1], last[0] - prev[0]);
  const ux = Math.cos(angle);
  const uy = Math.sin(angle);
  // Koniec trzonu tuż przed grotem.
  const shaftEnd: [number, number] = [last[0] - ux * head, last[1] - uy * head];
  const line = [...points.slice(0, -1), shaftEnd];
  const half = width / 2;
  const left: [number, number][] = [];
  const right: [number, number][] = [];
  for (let i = 0; i < line.length; i++) {
    const p = line[i] as [number, number];
    const q = line[Math.min(i + 1, line.length - 1)] as [number, number];
    const o = line[Math.max(i - 1, 0)] as [number, number];
    const a1 = Math.atan2(q[1] - p[1], q[0] - p[0]);
    const a0 = Math.atan2(p[1] - o[1], p[0] - o[0]);
    let nx: number;
    let ny: number;
    let scale = 1;
    if (i === 0) {
      nx = -Math.sin(a1);
      ny = Math.cos(a1);
    } else if (i === line.length - 1) {
      nx = -Math.sin(a0);
      ny = Math.cos(a0);
    } else {
      // Załamanie (strzałka skoczka): wspólna normalna, wydłużona tak, by trzon miał stałą grubość.
      const mid = (a0 + a1) / 2 + (Math.abs(a1 - a0) > Math.PI ? Math.PI : 0);
      nx = -Math.sin(mid);
      ny = Math.cos(mid);
      scale = 1 / Math.max(0.3, Math.cos((a1 - a0) / 2));
    }
    left.push([p[0] + nx * half * scale, p[1] + ny * half * scale]);
    right.push([p[0] - nx * half * scale, p[1] - ny * half * scale]);
  }
  const nx = -uy;
  const ny = ux;
  const tip = last;
  const baseL: [number, number] = [shaftEnd[0] + (nx * headWidth) / 2, shaftEnd[1] + (ny * headWidth) / 2];
  const baseR: [number, number] = [shaftEnd[0] - (nx * headWidth) / 2, shaftEnd[1] - (ny * headWidth) / 2];
  const outline = [...left, baseL, tip, baseR, ...right.reverse()];
  return "M" + outline.map(([x, y]) => `${x.toFixed(4)} ${y.toFixed(4)}`).join("L") + "Z";
}

/** "rgba(1,2,3,0.5)" → ["rgb(1,2,3)", 0.5] — przezroczystość nakładamy na całą strzałkę naraz. */
export function splitAlpha(color: string): [string, number] {
  const match = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\)/.exec(color);
  if (!match) return [color, 1];
  return [`rgb(${match[1]},${match[2]},${match[3]})`, match[4] !== undefined ? Number(match[4]) : 1];
}

export const easeInOutCubic = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
export const easeOutCubic = (t: number): number => 1 - (1 - Math.min(1, Math.max(0, t))) ** 3;
export function easeOutBack(t: number, overshoot = 1.70158): number {
  const x = Math.min(1, Math.max(0, t));
  const c3 = overshoot + 1;
  return 1 + c3 * (x - 1) ** 3 + overshoot * (x - 1) ** 2;
}
