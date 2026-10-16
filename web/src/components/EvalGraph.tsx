// Advantage graph after a game (like chess.com's Game Review): White's winning chance after every ply.
// The light area is White's share, the dark one Black's; clicking the graph jumps to that move.

import type { ReactElement } from "react";
import { BADGE_COLORS } from "./Badge";
import { useSize } from "./Charts";

/** Classes marked with a dot on the graph (only the player's moves). */
const MARKED = new Set(["brilliant", "great", "inaccuracy", "mistake", "blunder"]);

export function EvalGraph({
  evals,
  current,
  marks,
  onJump,
}: {
  evals: number[];
  current: number;
  /** Class of the player's move for every ply (index 0 = first move), null for the coach's moves. */
  marks: (string | null)[];
  onJump: (index: number) => void;
}): ReactElement {
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const n = evals.length;
  const w = Math.max(1, width);
  const h = Math.max(1, height);
  const px = (i: number): number => (n > 1 ? (w * i) / (n - 1) : 0);
  const py = (v: number): number => h * (1 - Math.min(100, Math.max(0, v)) / 100);
  const line = evals.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" L");
  const indexAt = (clientX: number, rect: DOMRect): number => Math.round(((clientX - rect.left) / Math.max(1, rect.width)) * (n - 1));
  return (
    <div
      className="eval-graph"
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-valuemin={0}
      aria-valuemax={n - 1}
      aria-valuenow={current}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        onJump(indexAt(event.clientX, event.currentTarget.getBoundingClientRect()));
      }}
      onPointerMove={(event) => {
        if (event.buttons !== 1) return;
        const index = indexAt(event.clientX, event.currentTarget.getBoundingClientRect());
        if (index !== current) onJump(index);
      }}
    >
      {width > 0 && n > 1 && (
        <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
          <rect x={0} y={0} width={w} height={h} className="eval-graph-black" />
          <path d={`M0,${h} L${line} L${w},${h} Z`} className="eval-graph-white" />
          <line x1={0} x2={w} y1={h / 2} y2={h / 2} className="eval-graph-mid" />
          <line x1={px(current)} x2={px(current)} y1={0} y2={h} className="eval-graph-cursor" />
          {marks.map((cls, i) =>
            cls && MARKED.has(cls) ? (
              <circle key={i} cx={px(i + 1)} cy={py(evals[i + 1] ?? 50)} r={4} fill={BADGE_COLORS[cls]} className="eval-graph-dot" />
            ) : null,
          )}
        </svg>
      )}
    </div>
  );
}
