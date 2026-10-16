// Puzzle modes: the mode picker (rated, theme training, review of mistakes, Puzzle Rush),
// the Puzzle Rush bar (clock, solved puzzles, mistakes) and the end-of-run summary.

import { useEffect, useState, type ReactElement } from "react";
import { screenAction } from "../api";
import { t, useLanguage } from "../i18n";
import type { RushState, Training } from "../types";
import { IconClose } from "./Icons";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("play", name, data);

/** Puzzle Rush variants: minutes on the clock, 0 = Survival. */
const RUSH_VARIANTS = [3, 5, 0];

function rushName(minutes: number): string {
  return minutes ? t("training.rush_minutes", { n: minutes }) : t("training.survival");
}

function useEscape(onClose: () => void): void {
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
}

export function ModeDialog({ training, onClose }: { training: Training; onClose: () => void }): ReactElement {
  useLanguage();
  useEscape(onClose);
  const [filter, setFilter] = useState("");
  const pick = (data: Record<string, unknown>): void => {
    onClose();
    act("training", data);
  };
  const needle = filter.trim().toLowerCase();
  const themes = training.themes.filter((theme) => !needle || theme.name.toLowerCase().includes(needle));
  return (
    <div className="modal-backdrop" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card mode-dialog" role="dialog" aria-modal="true" aria-label={t("training.title")}>
        <header className="mode-head">
          <h2>{t("training.title")}</h2>
          <button type="button" className="btn btn-secondary square compact" onClick={onClose} title={t("ui.close")}>
            <IconClose size={16} />
          </button>
        </header>
        <button type="button" className={`mode-option${training.kind === "rated" ? " active" : ""}`} onClick={() => pick({ kind: "rated" })}>
          <strong>{t("training.rated")}</strong>
          <span className="muted small">{t("training.rated_desc")}</span>
        </button>
        <section className={`mode-option static${training.kind === "rush" ? " active" : ""}`}>
          <strong>{t("training.rush")}</strong>
          <span className="muted small">{t("training.rush_desc")}</span>
          <div className="rush-variants">
            {RUSH_VARIANTS.map((minutes) => (
              <button key={minutes} type="button" className="btn btn-secondary" onClick={() => pick({ kind: "rush", minutes })}>
                <span>{rushName(minutes)}</span>
                {(training.rushBest[String(minutes)] ?? 0) > 0 && (
                  <span className="rush-best">{t("training.best", { n: training.rushBest[String(minutes)] ?? 0 })}</span>
                )}
              </button>
            ))}
          </div>
        </section>
        <button
          type="button"
          className={`mode-option${training.kind === "review" ? " active" : ""}`}
          disabled={training.review === 0}
          onClick={() => pick({ kind: "review" })}
        >
          <strong>
            {t("training.review")}
            {training.review > 0 && <span className="mode-count">{training.review}</span>}
          </strong>
          <span className="muted small">{training.review > 0 ? t("training.review_desc") : training.reviewLabel}</span>
        </button>
        <section className={`mode-option static${training.kind === "theme" ? " active" : ""}`}>
          <strong>{t("training.theme_title")}</strong>
          <span className="muted small">{t("training.theme_desc")}</span>
          <input
            className="theme-filter"
            type="search"
            value={filter}
            placeholder={t("training.theme_filter")}
            aria-label={t("training.theme_title")}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="theme-grid">
            {themes.map((theme) => (
              <button
                key={theme.id}
                type="button"
                className={`theme-chip${training.theme === theme.id ? " active" : ""}${theme.weak ? " weak" : ""}`}
                title={theme.name}
                onClick={() => pick({ kind: "theme", theme: theme.id })}
              >
                <span className="theme-chip-name">{theme.name}</span>
                <span className="theme-chip-meta">{theme.stats || theme.count}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function RushBar({ rush }: { rush: RushState }): ReactElement {
  useLanguage();
  const low = rush.left !== null && rush.left <= 30 && !rush.over;
  return (
    <section className="card rush-bar">
      <div className="rush-stat">
        <span className="muted small">{t("rush.time")}</span>
        <strong className={`rush-clock${low ? " low" : ""}`}>{rush.left === null ? "∞" : clock(rush.left)}</strong>
      </div>
      <div className="rush-stat">
        <span className="muted small">{t("rush.solved")}</span>
        <strong className="rush-score">{rush.solved}</strong>
      </div>
      <div className="rush-stat">
        <span className="muted small">{t("rush.strikes")}</span>
        <span className="rush-strikes" aria-label={`${rush.strikes}/${rush.maxStrikes}`}>
          {Array.from({ length: rush.maxStrikes }, (_, i) => (
            <span key={i} className={`strike${i < rush.strikes ? " on" : ""}`}>
              ✕
            </span>
          ))}
        </span>
      </div>
      <div className="rush-side">
        {rush.best > 0 && <span className="muted small">{t("training.best", { n: rush.best })}</span>}
        {!rush.over && (
          <button type="button" className="btn btn-secondary compact" onClick={() => act("rush_stop")}>
            {t("rush.stop")}
          </button>
        )}
      </div>
    </section>
  );
}

export function RushSummary({ rush }: { rush: RushState }): ReactElement {
  useLanguage();
  useEscape(() => act("rush_back"));
  return (
    <div className="modal-backdrop">
      <div className="modal card rush-summary" role="dialog" aria-modal="true">
        <h2>{rush.overTitle}</h2>
        <p className="rush-summary-score">{rush.solved}</p>
        <p className="soft">{rush.result}</p>
        {rush.record ? <p className="rush-record">{t("rush.record")}</p> : rush.best > 0 && <p className="muted">{t("training.best", { n: rush.best })}</p>}
        {rush.results.length > 0 && (
          <div className="rush-results">
            {rush.results.map((result, i) => (
              <span key={i} className={`rush-result${result.solved ? " ok" : " bad"}`} title={t("play.rating", { rating: result.rating })}>
                {result.rating}
              </span>
            ))}
          </div>
        )}
        <div className="modal-buttons">
          <button type="button" className="btn btn-secondary" onClick={() => act("rush_back")}>
            {t("rush.back")}
          </button>
          <button type="button" className="btn btn-primary" onClick={() => act("rush_again")}>
            {t("rush.again")}
          </button>
        </div>
      </div>
    </div>
  );
}
