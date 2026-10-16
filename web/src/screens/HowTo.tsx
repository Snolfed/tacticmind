// "How does the AI work?": minimax vs alpha-beta on the real engine, a step-by-step demonstration
// of cutoffs on a small tree and a description of the algorithms.

import { useState, type ReactElement } from "react";
import { screenAction } from "../api";
import { useSize } from "../components/Charts";
import { IconChevronLeft, IconChevronRight } from "../components/Icons";
import { Segmented } from "../components/Widgets";
import { useKeys } from "../hooks";
import { t, useLanguage } from "../i18n";
import type { DemoNode, HowToSnapshot } from "../types";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("howto", name, data);

function Compare({ view }: { view: HowToSnapshot }): ReactElement {
  const result = view.result;
  const colors = ["bad", "mid", "good"];
  return (
    <section className="card howto-card">
      <h2>{t("compare.title")}</h2>
      <p className="muted">{t("compare.subtitle")}</p>
      <div className="chip-row">
        <span className="chip-label">{t("compare.position")}</span>
        {view.positions.map((label, i) => (
          <button key={label} type="button" className={`btn chip ${i === view.position ? "btn-primary" : "btn-secondary"}`} onClick={() => act("position", { index: i })}>
            {label}
          </button>
        ))}
      </div>
      <div className="chip-row">
        <span className="chip-label">{t("compare.depth")}</span>
        {[1, 2, 3, 4].map((depth) => (
          <button key={depth} type="button" className={`btn chip square ${depth === view.depth ? "btn-primary" : "btn-secondary"}`} onClick={() => act("depth", { depth })}>
            {depth}
          </button>
        ))}
        <button type="button" className="btn btn-primary run-button" disabled={view.running} onClick={() => act("run")}>
          {view.running ? t("compare.running") : t("compare.run")}
        </button>
      </div>
      {view.status && <p className={view.error ? "tone-red" : "muted"}>{view.status}</p>}
      {result && (
        <div className="compare-result">
          <p className="muted bold">{result.label}</p>
          {result.rows.map((row, i) => (
            <div key={row.name} className="compare-row">
              <span className="compare-name">{row.name}</span>
              {row.skipped ? (
                <span className="muted compare-skipped">{row.skipped}</span>
              ) : (
                <>
                  <span className="bar-track">
                    <span className={`bar-fill ${colors[i]}`} style={{ width: `max(16px, ${((row.share ?? 0) * 100).toFixed(1)}%)` }} />
                  </span>
                  <span className="compare-stats">{row.stats}</span>
                </>
              )}
            </div>
          ))}
          <p className={result.same ? "tone-accent" : "tone-red"}>{result.summary}</p>
        </div>
      )}
    </section>
  );
}

interface Placed {
  node: DemoNode;
  x: number;
  y: number;
  depth: number;
}

function DemoTree({ tree, known, entered, cut, active }: { tree: DemoNode; known: Map<string, number>; entered: Set<string>; cut: Set<string>; active: string | null }): ReactElement {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const height = 250;
  const left = 56;
  const placed: Placed[] = [];
  const place = (node: DemoNode, depth: number, a: number, b: number): void => {
    placed.push({ node, x: (a + b) / 2, y: 24 + depth * 66, depth });
    node.children.forEach((child, i) => {
      const span = (b - a) / node.children.length;
      place(child, depth + 1, a + i * span, a + (i + 1) * span);
    });
  };
  place(tree, 0, left, Math.max(left + 100, width));
  const at = new Map(placed.map((p) => [p.node.id, p]));
  const r = 17;
  return (
    <div className="demo-tree" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height}>
          {["MAX", "MIN", "MAX", t("demo.leaves")].map((label, depth) => (
            <text key={depth} x={0} y={24 + depth * 66} dominantBaseline="central" className="tree-level">
              {label}
            </text>
          ))}
          {placed.flatMap(({ node, x, y }) =>
            node.children.map((child) => {
              const c = at.get(child.id) as Placed;
              const pruned = cut.has(child.id);
              const mx = (x + c.x) / 2;
              const my = (y + c.y) / 2;
              return (
                <g key={`e-${child.id}`}>
                  <line x1={x} y1={y + r} x2={c.x} y2={c.y - r} className={`tree-edge${pruned ? " pruned" : entered.has(child.id) ? " entered" : ""}`} />
                  {pruned && <path d={`M${mx - 7} ${my - 7}L${mx + 7} ${my + 7}M${mx - 7} ${my + 7}L${mx + 7} ${my - 7}`} className="tree-cut" />}
                </g>
              );
            }),
          )}
          {placed.map(({ node, x, y, depth }) => {
            const pruned = cut.has(node.id);
            const isActive = node.id === active;
            const value = node.value ?? known.get(node.id);
            const cls = `tree-node${pruned ? " pruned" : known.has(node.id) ? " known" : ""}${isActive ? " active" : ""}`;
            return (
              <g key={node.id} className={cls}>
                {isActive && <circle cx={x} cy={y} r={r * 2.2} className="tree-glow" />}
                {depth % 2 === 0 ? <circle cx={x} cy={y} r={r} /> : <rect x={x - r} y={y - r} width={2 * r} height={2 * r} rx={6} />}
                <text x={x} y={y} textAnchor="middle" dominantBaseline="central">
                  {value === undefined || value === null ? "?" : Math.round(value)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

function Demo({ view, step, setStep }: { view: HowToSnapshot; step: number; setStep: (step: number) => void }): ReactElement {
  const [mode, setMode] = useState<"minimax" | "alphabeta">("alphabeta");
  const demo = view.demos[mode];
  const total = demo.steps.length;
  const shown = Math.min(step, total);
  const steps = demo.steps.slice(0, shown);
  const known = new Map<string, number>();
  const entered = new Set<string>();
  const cut = new Set<string>();
  for (const s of steps) {
    entered.add(s.node);
    if (s.value !== null) known.set(s.node, s.value);
    s.cut.forEach((id) => cut.add(id));
  }
  const last = steps[steps.length - 1];
  let text = last ? t("demo.step", { i: shown, n: total, text: last.text }) : t("demo.start", { n: total });
  if (shown >= total) text += "  " + demo.result;
  return (
    <section className="card howto-card">
      <header className="demo-head">
        <h2>{t("demo.title")}</h2>
        <Segmented
          options={(["minimax", "alphabeta"] as const).map((value) => ({ value, label: t(`demo.${value}`) }))}
          value={mode}
          onChange={(value) => {
            setMode(value);
            setStep(0);
          }}
        />
      </header>
      <p className="muted">{t("demo.explain")}</p>
      <DemoTree tree={view.tree} known={known} entered={entered} cut={cut} active={last?.node ?? null} />
      <div className="demo-foot">
        <p className="demo-text">{text}</p>
        <div className="demo-buttons">
          <button type="button" className="btn btn-secondary" onClick={() => setStep(0)}>
            {t("demo.reset")}
          </button>
          <button type="button" className="btn btn-secondary square" onClick={() => setStep(Math.max(0, shown - 1))} disabled={shown <= 0}>
            <IconChevronLeft />
          </button>
          <button type="button" className="btn btn-secondary square" onClick={() => setStep(Math.min(total, shown + 1))} disabled={shown >= total}>
            <IconChevronRight />
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setStep(total)}>
            {t("demo.all")}
          </button>
        </div>
      </div>
    </section>
  );
}

export function HowTo({ view }: { view: HowToSnapshot }): ReactElement {
  useLanguage();
  const [step, setStep] = useState(0);
  const maxSteps = Math.max(view.demos.minimax.steps.length, view.demos.alphabeta.steps.length);
  useKeys((event) => {
    if (event.key === "ArrowRight") setStep((s) => Math.min(maxSteps, s + 1));
    else if (event.key === "ArrowLeft") setStep((s) => Math.max(0, s - 1));
    else return;
    event.preventDefault();
  });
  return (
    <div className="screen howto">
      <article className="howto-page">
        <h1>{t("howto.title")}</h1>
        <p className="lead">{t("howto.intro")}</p>
        <Compare view={view} />
        <Demo view={view} step={Math.min(step, maxSteps)} setStep={setStep} />
        {view.sections.map((key) =>
          key === "code" ? (
            <section key={key} className="howto-section">
              <h2 className="plain">{t("howto.code.title")}</h2>
              <pre className="code">{t("howto.code")}</pre>
            </section>
          ) : (
            <section key={key} className="howto-section">
              <h2>{t(`howto.${key}.title`)}</h2>
              <p>{t(`howto.${key}.body`)}</p>
            </section>
          ),
        )}
      </article>
    </div>
  );
}
