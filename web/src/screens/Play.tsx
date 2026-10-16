// Puzzle screen: board with the evaluation bar, puzzle card, buttons and the "AI Brain" panel.

import { useEffect, useState, type ReactElement } from "react";
import { screenAction } from "../api";
import { Board } from "../components/Board";
import { BrainPanel } from "../components/BrainPanel";
import { EvalBar } from "../components/EvalBar";
import { IconChevronLeft, IconChevronRight, IconClose } from "../components/Icons";
import { ConfirmDialog } from "../components/Widgets";
import { useKeys } from "../hooks";
import { t, useLanguage } from "../i18n";
import type { PlaySnapshot } from "../types";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("play", name, data);

function PuzzleCard({ view }: { view: PlaySnapshot }): ReactElement {
  const card = view.card;
  const [why, setWhy] = useState(false);
  useEffect(() => setWhy(false), [view.puzzle]);
  return (
    <section className="card puzzle-card">
      <div className="puzzle-head">
        <span className={`side-dot ${card.side}`} />
        <span className="puzzle-title">{card.title}</span>
        <span className={`puzzle-rating${card.finished ? "" : " dim"}`}>{card.rating}</span>
      </div>
      <p key={card.messageSeq} className={`puzzle-message tone-${card.color}`}>
        {card.message}
      </p>
      {card.detail && <p className="puzzle-detail">{card.detail}</p>}
      <div className="puzzle-foot">
        {card.finished ? (
          <>
            <span className="puzzle-themes">{card.themes}</span>
            {card.delta !== null && <span className={`puzzle-delta ${card.delta >= 0 ? "up" : "down"}`}>{card.delta >= 0 ? `+${card.delta}` : `−${Math.abs(card.delta)}`}</span>}
          </>
        ) : (
          card.why.length > 0 && (
            <button type="button" className={`link-button${why ? " active" : ""}`} onClick={() => setWhy(!why)}>
              {t("play.why")}
            </button>
          )
        )}
      </div>
      {why && !card.finished && (
        <div className="why-popover card" onClick={() => setWhy(false)}>
          <h3>{t("play.why")}</h3>
          <ul>
            {card.why.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Controls({ view }: { view: PlaySnapshot }): ReactElement {
  const b = view.buttons;
  if (view.preview) {
    const preview = view.preview;
    return (
      <div className="controls-row preview-bar">
        <div className="preview-text">
          <span className="preview-label">{preview.label}</span>
          <span className="preview-line">{preview.line}</span>
        </div>
        <button type="button" className="btn btn-secondary square" onClick={() => act("step", { delta: -1 })} disabled={preview.index <= 0} title={t("ui.prev")}>
          <IconChevronLeft />
        </button>
        <button type="button" className="btn btn-secondary square" onClick={() => act("step", { delta: 1 })} disabled={preview.index >= preview.total} title={t("ui.next")}>
          <IconChevronRight />
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => act("preview_close")}>
          <IconClose size={16} />
          {t("play.preview_back")}
        </button>
      </div>
    );
  }
  const actions: { id: "hint" | "solution" | "retry" | "next"; long: string; short: string; style: string }[] = [
    { id: "hint", long: "play.btn.hint", short: "play.btn.hint", style: "secondary" },
    { id: "solution", long: "play.btn.solution", short: "play.btn.solution_short", style: "secondary" },
    { id: "retry", long: "play.btn.retry", short: "play.btn.retry_short", style: "secondary" },
    { id: "next", long: "play.btn.next", short: "play.btn.next_short", style: "primary" },
  ];
  return (
    <div className="controls-row">
      {b.prev.visible && (
        <>
          <button type="button" className="btn btn-secondary square" disabled={!b.prev.enabled} onClick={() => act("step", { delta: -1 })} title={t("ui.prev")}>
            <IconChevronLeft />
          </button>
          <button type="button" className="btn btn-secondary square" disabled={!b.fwd.enabled} onClick={() => act("step", { delta: 1 })} title={t("ui.next")}>
            <IconChevronRight />
          </button>
        </>
      )}
      {actions
        .filter((action) => b[action.id].visible)
        .map((action) => (
          <button key={action.id} type="button" className={`btn btn-${action.style} grow`} disabled={!b[action.id].enabled} onClick={() => act(action.id)}>
            <span className="label-long">{t(action.long)}</span>
            <span className="label-short">{t(action.short)}</span>
          </button>
        ))}
    </div>
  );
}

export function Play({ view }: { view: PlaySnapshot }): ReactElement {
  useLanguage();
  useKeys((event) => {
    if (!view.board) return;
    if (event.key === "ArrowLeft") act("step", { delta: -1 });
    else if (event.key === "ArrowRight") act("step", { delta: 1 });
    else if (event.key === "Escape" && view.preview) act("preview_close");
    else if (event.key === "Enter" && view.buttons?.next.visible && !view.preview) act("next");
    else return;
    event.preventDefault();
  });
  if (!view.board) return <div className="screen play loading" />;
  const evalProps = { hidden: view.eval.hidden, score: view.eval.score, whiteBottom: view.eval.whiteBottom };
  return (
    <div className="screen play">
      <div className="play-main">
        <div className="eval-horizontal">
          <EvalBar {...evalProps} horizontal />
        </div>
        <div className="board-row">
          <div className="eval-vertical">
            <EvalBar {...evalProps} />
          </div>
          <Board board={view.board} name="play" onMove={(uci) => act("move", { uci })} />
        </div>
        <Controls view={view} />
      </div>
      <div className="play-side">
        <PuzzleCard view={view} />
        <BrainPanel
          brain={view.brain}
          onMode={(mode) => act("mode", { mode })}
          onPreview={(index) => act("preview", { index })}
          resetKey={view.puzzle}
        />
      </div>
      {view.confirm && <ConfirmDialog text={view.confirm.text} yes={view.confirm.yes} onYes={() => act("confirm_yes")} onNo={() => act("confirm_no")} />}
    </div>
  );
}
