// Pasek oceny: biała część rośnie sprężyście, wartość (+1.5, M3) po stronie, która wygrywa.

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
  // Bez nowej oceny pasek zostaje tam, gdzie był (jak w wersji pygame).
  const last = useRef<{ share: number; label: string; white: boolean }>({ share: 0.5, label: "0.0", white: true });
  if (score) last.current = { share: whiteShare(score), label: score.label.replace(/^[+-]/, ""), white: score.value >= 0 };
  const { share, label, white } = last.current;
  const atStart = white === whiteBottom; // wartość przy dolnej (lewej) krawędzi
  return (
    <div className={`eval-bar${horizontal ? " horizontal" : ""}${hidden ? " hidden" : ""}`} aria-label={hidden ? "?" : label}>
      {hidden ? (
        <span className="eval-question">?</span>
      ) : (
        <>
          <div className={`eval-white${whiteBottom ? " from-start" : " from-end"}`} style={{ "--share": share } as React.CSSProperties} />
          <div className="eval-mid" />
          <span className={`eval-label${atStart ? " at-start" : " at-end"}${white ? " on-white" : " on-black"}`}>{label}</span>
        </>
      )}
    </div>
  );
}
