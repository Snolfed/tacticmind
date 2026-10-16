// The "AI Brain" panel: live counters, the 3 best moves, the thought stream and the search tree.

import { useEffect, useLayoutEffect, useRef, useState, type ReactElement } from "react";
import { t, useLanguage } from "../i18n";
import type { BrainSnapshot, TreeRoot } from "../types";
import { Segmented } from "./Widgets";

const MODES = ["hidden", "hint", "full"] as const;

function BrainIcon({ running }: { running: boolean }): ReactElement {
  const nodes: [number, number][] = [
    [4.3, 15],
    [19.7, 15],
    [12, 4.3],
  ];
  return (
    <svg className={`brain-icon${running ? " running" : ""}`} width="24" height="22" viewBox="0 0 24 20" aria-hidden="true">
      <g stroke="rgba(255,106,168,0.55)" strokeWidth="2">
        <line x1={4.3} y1={15} x2={19.7} y2={15} />
        <line x1={4.3} y1={15} x2={12} y2={4.3} />
        <line x1={19.7} y1={15} x2={12} y2={4.3} />
      </g>
      {nodes.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={3.6} fill="rgb(255,106,168)" style={{ animationDelay: `${-i * 0.35}s` }} />
      ))}
    </svg>
  );
}

function Thinking(): ReactElement {
  return (
    <span className="thinking-dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}

/** A scrolling list that follows new entries to the bottom (unless the user has scrolled up). */
function useStickToBottom(dependency: unknown): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = (): void => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [dependency]);
  return ref;
}

function Tree({ roots }: { roots: TreeRoot[] }): ReactElement {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const key = roots.map((r) => r.move).join(" ");
  // Initially expand the first move and the first one where alpha-beta pruned something — so a cutoff is visible.
  useEffect(() => {
    const initial = new Set<string>();
    if (roots[0]) initial.add(roots[0].move);
    const withCut = roots.slice(1).find((root) => root.children.some((child) => child.pruned));
    if (withCut) initial.add(withCut.move);
    setExpanded(initial);
  }, [key]);
  return (
    <div className="tree">
      <p className="tree-legend">{t("brain.tree.legend")}</p>
      {roots.map((root) => {
        const open = expanded.has(root.move);
        return (
          <div key={root.move} className="tree-root">
            <button
              type="button"
              className={`tree-row root${root.pruned ? " pruned" : ""}`}
              onClick={() => {
                const next = new Set(expanded);
                if (open) next.delete(root.move);
                else next.add(root.move);
                setExpanded(next);
              }}
            >
              <span className={`caret${open ? " open" : ""}`} aria-hidden="true" />
              <span className="tree-san">{root.san}</span>
              <span className={`tree-value${root.exact ? "" : " bound"}`}>
                {root.pruned ? t("brain.tree.pruned") : root.value + (root.tt ? "  " + t("brain.tree.tt") : "")}
              </span>
            </button>
            {open && (
              <div className="tree-children">
                {root.children.map((child, i) => (
                  <div key={child.move + i} className={`tree-row child${child.pruned ? " pruned" : ""}`}>
                    <span className="tree-san">{child.san}</span>
                    <span className={`tree-value${child.exact ? "" : " bound"}`}>
                      {child.pruned ? t("brain.tree.pruned") : child.value + (child.tt ? "  " + t("brain.tree.tt") : "")}
                    </span>
                  </div>
                ))}
                {root.more > 0 && <div className="tree-more">{t("brain.tree.more", { n: root.more })}</div>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function BrainPanel({
  brain,
  onMode,
  onPreview,
  previewIndex = null,
  resetKey,
}: {
  brain: BrainSnapshot;
  onMode: (mode: string) => void;
  onPreview: (index: number) => void;
  previewIndex?: number | null;
  /** New puzzle — switch back to the "Thought stream" tab. */
  resetKey?: number;
}): ReactElement {
  useLanguage();
  const [tab, setTab] = useState<"thoughts" | "tree">("thoughts");
  useEffect(() => setTab("thoughts"), [resetKey]);
  const reveal = brain.mode === "full";
  const scroller = useStickToBottom(`${brain.thoughts.length}:${brain.explanation.length}:${tab}`);
  const candidates = brain.candidates;

  return (
    <section className="card brain">
      <header className="brain-header">
        <BrainIcon running={brain.running} />
        <h2>{t("brain.title")}</h2>
        <span className="brain-status">
          {brain.running ? (
            <>
              <Thinking /> {t("brain.thinking")}
            </>
          ) : (
            <span className="dim">{brain.hasInfo ? t("brain.ready") : t("brain.waiting")}</span>
          )}
        </span>
        <Segmented
          className="brain-modes"
          options={MODES.map((mode) => ({ value: mode, label: t(`brain.mode.${mode}`) }))}
          value={brain.mode}
          onChange={onMode}
        />
      </header>

      <div className="counters">
        {brain.counters.map((counter) => (
          <div key={counter.label} className="counter">
            <span className="counter-label">{counter.label}</span>
            <span className="counter-value">{counter.value}</span>
          </div>
        ))}
      </div>

      <h3 className="section-label">{t("brain.best_moves")}</h3>
      <div className="candidates">
        {[0, 1, 2].map((i) => {
          if (!candidates) {
            return (
              <div key={i} className="candidate hidden">
                <span className="score-pill hidden">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="candidate-line dim">{t("brain.hidden_line")}</span>
              </div>
            );
          }
          const line = candidates[i];
          if (!line) {
            return (
              <div key={i} className="candidate empty">
                <span className="score-pill empty" />
                <span className="candidate-line dim">—</span>
              </div>
            );
          }
          return (
            <button
              key={i}
              type="button"
              className={`candidate${i === 0 ? " best" : ""}${previewIndex === i ? " active" : ""}`}
              onClick={() => onPreview(i)}
            >
              <span className={`score-pill ${line.white ? "white" : "black"}`}>{line.score}</span>
              <span className="candidate-line">{line.line}</span>
            </button>
          );
        })}
      </div>

      <div className="tabs" role="tablist" style={{ "--tab": tab === "thoughts" ? 0 : 1 } as React.CSSProperties}>
        {(["thoughts", "tree"] as const).map((name) => (
          <button key={name} type="button" role="tab" aria-selected={tab === name} className={tab === name ? "selected" : ""} onClick={() => setTab(name)}>
            {t(`brain.tab.${name}`)}
          </button>
        ))}
      </div>

      <div className="brain-content" ref={scroller}>
        {tab === "thoughts" ? (
          <>
            {reveal && brain.explanation.length > 0 && (
              <>
                <h4 className="thoughts-header accent">{t("brain.explains")}</h4>
                {brain.explanation.map((line, i) => (
                  <p key={`x${i}`} className="thought explain">
                    {line}
                  </p>
                ))}
                <h4 className="thoughts-header">{t("brain.tab.thoughts")}</h4>
              </>
            )}
            {!reveal && <p className="thought note">{brain.statusNote || t("brain.analyzing")}</p>}
            {brain.thoughts.map((thought, i) => (
              <p key={i} className={`thought kind-${thought.kind}`}>
                {thought.text}
              </p>
            ))}
          </>
        ) : !reveal ? (
          <p className="muted">{t("brain.tree.hidden")}</p>
        ) : !brain.tree || !brain.tree.length ? (
          <p className="muted">{t("brain.tree.nodata")}</p>
        ) : (
          <Tree roots={brain.tree} />
        )}
      </div>
    </section>
  );
}
