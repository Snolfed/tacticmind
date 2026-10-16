// Move badges (as in chess.com's "Game Review"): !!, !, ★, ✓, book, ?!, ?, ?? plus ✓ / ✗ in puzzles.

import type { ReactElement } from "react";

export const BADGE_COLORS: Record<string, string> = {
  brilliant: "rgb(46,230,200)",
  great: "rgb(96,145,250)",
  best: "rgb(52,211,153)",
  excellent: "rgb(110,200,120)",
  good: "rgb(140,168,132)",
  book: "rgb(196,156,112)",
  inaccuracy: "rgb(245,192,50)",
  mistake: "rgb(251,146,60)",
  blunder: "rgb(255,81,72)",
  ok: "rgb(198,241,53)",
  bad: "rgb(255,81,72)",
};

const GLYPHS: Record<string, string> = { brilliant: "!!", great: "!", inaccuracy: "?!", mistake: "?", blunder: "??" };

function star(outer: number, inner: number): string {
  const points: string[] = [];
  for (let i = 0; i < 10; i++) {
    const r = i % 2 === 0 ? outer : inner;
    const angle = -Math.PI / 2 + (i * Math.PI) / 5;
    points.push(`${(Math.cos(angle) * r).toFixed(3)},${(Math.sin(angle) * r).toFixed(3)}`);
  }
  return points.join(" ");
}

const STAR = star(0.62, 0.28);
const BOOK_W = 0.684;
const BOOK_H = 0.494;
const BOOK_LEFT: [number, number][] = [
  [-BOOK_W, -BOOK_H * 0.8],
  [-BOOK_W * 0.15, -BOOK_H],
  [0, -BOOK_H * 0.7],
  [0, BOOK_H],
  [-BOOK_W * 0.15, BOOK_H * 0.75],
  [-BOOK_W, BOOK_H],
];
const pts = (list: [number, number][]): string => list.map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(" ");

function Glyph({ kind }: { kind: string }): ReactElement | null {
  if (GLYPHS[kind]) return null; // text is drawn outside the scaled group (see Badge)
  if (kind === "best") return <polygon points={STAR} fill="#fff" />;
  if (kind === "book") {
    return (
      <g fill="#fff">
        <polygon points={pts(BOOK_LEFT)} />
        <polygon points={pts(BOOK_LEFT.map(([x, y]) => [-x, y]))} />
      </g>
    );
  }
  if (kind === "bad") {
    return <path d="M-0.4 -0.4L0.4 0.4M0.4 -0.4L-0.4 0.4" stroke="#fff" strokeWidth={0.22} strokeLinecap="round" />;
  }
  const color = kind === "ok" ? "rgb(18,16,13)" : "#fff";
  return <polyline points="-0.46,0.02 -0.14,0.34 0.46,-0.3" fill="none" stroke={color} strokeWidth={0.22} strokeLinecap="round" strokeLinejoin="round" />;
}

/** A round badge; ``kind`` = move class (best, blunder…) or ok / bad. */
export function Badge({ kind, size = 22, className }: { kind: string; size?: number; className?: string }): ReactElement {
  const color = BADGE_COLORS[kind] ?? "rgb(142,150,175)";
  const glyph = GLYPHS[kind];
  return (
    <svg className={className} width={size} height={size} viewBox="-58 -56 116 120" aria-hidden="true">
      <g transform="scale(50)">
        <circle cx="0.1" cy="0.12" r="1.06" fill="rgba(10,8,5,0.6)" />
        <circle cx="0" cy="0" r="1" fill={color} />
        <Glyph kind={kind} />
      </g>
      {glyph && (
        // Font at normal scale — browsers render very small font sizes in SVG inaccurately.
        <text x="0" y="3" textAnchor="middle" dominantBaseline="central" fontSize={glyph.length > 1 ? 56 : 68} fontWeight={700} fill="#fff">
          {glyph}
        </text>
      )}
    </svg>
  );
}
