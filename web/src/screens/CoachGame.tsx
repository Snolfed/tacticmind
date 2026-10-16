// Game against the coach: board with player bars, coach card with a comment, move list,
// game summary.

import { useEffect, useLayoutEffect, useRef, type ReactElement } from "react";
import { go, screenAction, send } from "../api";
import { BADGE_COLORS, Badge } from "../components/Badge";
import { Board, pieceUrl } from "../components/Board";
import { CoachAvatar } from "../components/CoachAvatar";
import { EvalBar } from "../components/EvalBar";
import { EvalGraph } from "../components/EvalGraph";
import { IconChevronLeft, IconChevronRight, IconEvalBar } from "../components/Icons";
import { ConfirmDialog } from "../components/Widgets";
import { useKeys } from "../hooks";
import { t, useLanguage } from "../i18n";
import type { CoachGameSnapshot, Strip } from "../types";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("coach_game", name, data);

function PlayerIcon(): ReactElement {
  return (
    <svg className="player-icon" viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <linearGradient id="player-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(198,241,53)" />
          <stop offset="1" stopColor="rgb(146,190,20)" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="20" r="20" fill="url(#player-bg)" />
      <circle cx="20" cy="15.5" r="6.5" fill="rgba(18,16,13,0.88)" />
      <path d="M8 34c1.8-6.5 6.6-10 12-10s10.2 3.5 12 10" fill="rgba(18,16,13,0.88)" />
    </svg>
  );
}

function StripRow({ strip, expression }: { strip: Strip; expression: string }): ReactElement {
  const prefix = strip.capturedColor === "white" ? "w" : "b";
  return (
    <div className={`strip${strip.toMove ? " to-move" : ""}`}>
      <span className={`strip-avatar${strip.player ? "" : " coach"}`}>{strip.player ? <PlayerIcon /> : <CoachAvatar expression={expression} size={32} />}</span>
      <span className="strip-name">{strip.name}</span>
      <span className="strip-detail">{strip.detail}</span>
      {strip.toMove && <span className="strip-turn" />}
      <span className="strip-captured">
        {strip.captured.map((symbol, i) => (
          <img key={i} src={pieceUrl(prefix + symbol.toUpperCase())} alt="" draggable={false} />
        ))}
        {strip.diff > 0 && <span className="strip-diff">+{strip.diff}</span>}
      </span>
    </div>
  );
}

function CoachCard({ view }: { view: CoachGameSnapshot }): ReactElement {
  const card = view.card;
  const comment = card.comment;
  return (
    <section className="card coach-card">
      <header className="coach-card-head">
        <span key={comment.seq} className="coach-card-avatar">
          <CoachAvatar expression={view.expression} size={66} />
        </span>
        <div>
          <h2>{t("coach.name")}</h2>
          <p className="muted small">{card.subtitle}</p>
          {card.opening && <p className="opening-name-tag">{card.opening}</p>}
        </div>
      </header>
      <div key={`c${comment.seq}-${comment.text}`} className={`bubble comment${comment.seq >= 0 ? " pop" : ""}`}>
        {comment.cls && (
          <div className="comment-cls" style={{ color: BADGE_COLORS[comment.cls] }}>
            <Badge kind={comment.cls} size={24} />
            {t(`cls.${comment.cls}`)}
          </div>
        )}
        <p>{comment.text}</p>
      </div>
      {card.side && (
        <div className={`side-note${card.side.threat ? " threat" : ""}${card.side.busy ? " busy" : ""}`}>
          <span className="dot-violet" />
          <span>
            {card.side.text}
            {card.side.busy && <span className="ellipsis" />}
          </span>
        </div>
      )}
      {card.buttons.length > 0 && (
        <div className="card-buttons">
          {card.buttons.map((button) => (
            <button key={button.id} type="button" className={`btn btn-${button.style}`} onClick={() => act(button.id)}>
              {button.label}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function MoveList({ view }: { view: CoachGameSnapshot }): ReactElement {
  const moves = view.moves;
  const scroller = useRef<HTMLDivElement>(null);
  const rows = Math.ceil((moves.list.length + moves.offset) / 2);
  useLayoutEffect(() => {
    const el = scroller.current;
    const current = el?.querySelector(".move-cell.current");
    if (el && current) {
      const box = current.getBoundingClientRect();
      const area = el.getBoundingClientRect();
      if (box.top < area.top || box.bottom > area.bottom) current.scrollIntoView({ block: "nearest" });
    } else if (el && moves.current >= moves.list.length - 1) {
      el.scrollTop = el.scrollHeight;
    }
  }, [moves.current, moves.list.length]);
  return (
    <section className="card move-list">
      <h3>{t("coach.moves")}</h3>
      <div className="moves" ref={scroller}>
        {Array.from({ length: rows }, (_, row) => (
          <div key={row} className="move-row">
            <span className="move-number">{moves.first + row}.</span>
            {[0, 1].map((col) => {
              const index = row * 2 + col - moves.offset;
              const record = moves.list[index];
              if (!record) return <span key={col} className="move-cell empty" />;
              return (
                <button
                  key={col}
                  type="button"
                  className={`move-cell${index === moves.current ? " current" : ""}${record.player ? " player" : ""}`}
                  onClick={() => act("jump", { index: index + 1 })}
                >
                  {record.cls && <Badge kind={record.cls} size={18} />}
                  <span>{record.san}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}

function ReviewCard({ view }: { view: CoachGameSnapshot }): ReactElement | null {
  const review = view.review;
  if (!review) return null;
  const copy = (): void => {
    navigator.clipboard
      ?.writeText(review.pgn)
      .then(() => act("pgn_copied"))
      .catch(() => act("pgn_save"));
  };
  return (
    <section className="card review-card">
      <header className="review-head">
        <h3>{t("coach.review.graph")}</h3>
        <div className="review-buttons">
          <button type="button" className="btn btn-secondary compact" onClick={copy}>
            {t("coach.btn.pgn_copy")}
          </button>
          <button type="button" className="btn btn-secondary compact" onClick={() => act("pgn_save")}>
            {t("coach.btn.pgn_save")}
          </button>
        </div>
      </header>
      <EvalGraph
        evals={review.evals}
        current={review.current}
        marks={view.moves.list.map((move) => (move.player ? move.cls : null))}
        onJump={(index) => act("jump", { index })}
      />
      <p className="muted small">{t("coach.review.graph_hint")}</p>
    </section>
  );
}

function Summary({ summary }: { summary: NonNullable<CoachGameSnapshot["summary"]> }): ReactElement {
  const expression = summary.result === "win" ? "excited" : summary.result === "loss" ? "happy" : "neutral";
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") act("review");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="modal-backdrop">
      <div className="modal card summary" role="dialog" aria-modal="true">
        <header className="summary-head">
          <CoachAvatar expression={expression} size={76} />
          <div>
            <h2 className={`result-${summary.result}`}>{summary.title}</h2>
            {summary.reason && <p className="soft">{summary.reason}</p>}
          </div>
        </header>
        <div className="summary-accuracy">
          {summary.accuracy.map((item) => (
            <div key={item.label}>
              <span className="muted">{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
        <p className="summary-caption">{t("coach.summary.accuracy")}</p>
        <div className="summary-rows">
          {summary.rows.map((row) => (
            <div key={row.cls} className="summary-row">
              <strong>{row.you}</strong>
              <span className="summary-cls" style={{ color: BADGE_COLORS[row.cls] }}>
                <Badge kind={row.cls} size={20} />
                {t(`cls.${row.cls}`)}
              </span>
              <strong className="soft">{row.trainer}</strong>
            </div>
          ))}
        </div>
        {summary.lines.map((line, i) => (
          <p key={i} className={`summary-line tone-${line.color}`}>
            {line.text}
          </p>
        ))}
        <div className="modal-buttons three">
          <button type="button" className="btn btn-secondary" onClick={() => act("review")}>
            {t("coach.btn.review")}
          </button>
          <button type="button" className="btn btn-primary" onClick={() => act("rematch")}>
            {t("coach.btn.rematch")}
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => act("menu")}>
            {t("coach.btn.menu")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CoachGame({ view, evalBar }: { view: CoachGameSnapshot; evalBar: boolean }): ReactElement {
  useLanguage();
  useKeys((event) => {
    if (!view.board || view.summary) return;
    if (event.key === "ArrowLeft") act("step", { delta: -1 });
    else if (event.key === "ArrowRight") act("step", { delta: 1 });
    else return;
    event.preventDefault();
  });
  if (!view.board) {
    return (
      <div className="screen coach-game loading">
        <button type="button" className="btn btn-secondary" onClick={() => go("coach")}>
          {t("nav.coach")}
        </button>
      </div>
    );
  }
  const [top, bottom] = view.strips;
  const evalProps = { hidden: false, score: view.eval.score, whiteBottom: view.eval.whiteBottom };
  return (
    <div className="screen coach-game">
      <div className="game-main">
        {top && <StripRow strip={top} expression={view.expression} />}
        {evalBar && (
          <div className="eval-horizontal">
            <EvalBar {...evalProps} horizontal />
          </div>
        )}
        <div className="coach-board">
          {evalBar && (
            <div className="eval-vertical">
              <EvalBar {...evalProps} />
            </div>
          )}
          <Board board={view.board} name="coach" onMove={(uci) => act("move", { uci })} />
        </div>
        {bottom && <StripRow strip={bottom} expression={view.expression} />}
        <div className="controls-row">
          <button type="button" className="btn btn-secondary square" disabled={!view.nav.prev} onClick={() => act("step", { delta: -1 })} title={t("ui.prev")}>
            <IconChevronLeft />
          </button>
          <button type="button" className="btn btn-secondary square" disabled={!view.nav.next} onClick={() => act("step", { delta: 1 })} title={t("ui.next")}>
            <IconChevronRight />
          </button>
          <button
            type="button"
            className="btn btn-secondary square"
            aria-pressed={evalBar}
            onClick={() => send({ type: "settings", coachEval: !evalBar })}
            title={t("ui.eval_bar")}
          >
            <IconEvalBar off={!evalBar} />
          </button>
          {view.controls.map((control) => (
            <button key={control.id} type="button" className={`btn btn-${control.style} grow`} disabled={!control.enabled} onClick={() => act(control.id)}>
              <span className="label-long">{control.label}</span>
              <span className="label-short">{control.short}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="game-side">
        <CoachCard view={view} />
        <ReviewCard view={view} />
        <MoveList view={view} />
      </div>
      {view.notice && (
        <div className="notice" role="status">
          {view.notice}
        </div>
      )}
      {view.summary && <Summary summary={view.summary} />}
      {view.confirm && <ConfirmDialog text={view.confirm.text} yes={view.confirm.yes} onYes={() => act("confirm_yes")} onNo={() => act("confirm_no")} />}
    </div>
  );
}
