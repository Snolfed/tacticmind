// Evaluation bar: the white part grows with a spring, the value (+1.5, M3) on the winning side; under the pointer the
// exact evaluation (+0.37) shows at the border between white and black, like on chess.com.

import { useRef, type ReactElement } from "react";
import type { Score } from "../types";

export function whiteShare(score: Score): number {
  if (score.mate !== null) {
    if (score.mate === 0) return score.value > 0 ? 1 : 0;
    return score.mate > 0 ? 1 : 0;
  }
  const cp = score.cp ?? 0;
  const share = 0.5 + 0.5 * (2 / (1 + Math.exp(-0.0042 * cp)) - 1);
  return Math.min(0.97, Math.max(0.03, share));
}

/** The evaluation to two decimals, like chess.com's tooltip: +0.37, -1.20, 0.00, M3, -M2. */
export function exactLabel(score: Score): string {
  if (score.mate !== null) return score.label;
  const pawns = (score.cp ?? 0) / 100;
  const text = Math.abs(pawns).toFixed(2);
  return text === "0.00" ? text : `${pawns > 0 ? "+" : "-"}${text}`;
}

export function EvalBar({
  hidden,
  score,
  whiteBottom,
  horizontal = false,
}: {
  hidden: boolean;
  score: Score | null;
  whiteBottom: boolean;
  horizontal?: boolean;
}): ReactElement {
  // Without a new evaluation the bar stays where it was.
  const last = useRef<{ share: number; label: string; exact: string; white: boolean }>({ share: 0.5, label: "0.0", exact: "0.00", white: true });
  if (score) last.current = { share: whiteShare(score), label: score.label.replace(/^[+-]/, ""), exact: exactLabel(score), white: score.value >= 0 };
  const { share, label, exact, white } = last.current;
  const side = whiteBottom ? " from-start" : " from-end";
  const atStart = white === whiteBottom; // value at the bottom (left) edge
  return (
    <div className={`eval-bar${horizontal ? " horizontal" : ""}${hidden ? " hidden" : ""}`} aria-label={hidden ? "?" : label}>
      {hidden ? (
        <span className="eval-question">?</span>
      ) : (
        <>
          <div className="eval-fill">
            <div className={`eval-white${side}`} style={{ "--share": share } as React.CSSProperties} />
            <div className="eval-mid" />
            <span className={`eval-label${atStart ? " at-start" : " at-end"}${white ? " on-white" : " on-black"}`}>{label}</span>
          </div>
          <span className={`eval-exact${side}`} style={{ "--share": share } as React.CSSProperties}>
            {exact}
          </span>
        </>
      )}
    </div>
  );
}
