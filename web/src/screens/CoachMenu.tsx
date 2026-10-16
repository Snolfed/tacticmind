// The "Coach" screen: greeting, coach strength (Elo or "Your level"), colour and openings to learn.

import { useEffect, useState, type ReactElement } from "react";
import { screenAction } from "../api";
import { CoachAvatar } from "../components/CoachAvatar";
import { ConfirmDialog, Segmented } from "../components/Widgets";
import { useKeys } from "../hooks";
import { t, useLanguage } from "../i18n";
import type { CoachMenuSnapshot } from "../types";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("coach", name, data);

function Stars({ count }: { count: number }): ReactElement {
  return (
    <span className="stars" aria-label={`${count}/3`}>
      {[0, 1, 2].map((i) => (
        <svg key={i} viewBox="-1 -1 2 2" width="16" height="16" className={i < count ? "on" : "off"}>
          <polygon points="0,-1 0.235,-0.324 0.951,-0.309 0.38,0.124 0.588,0.809 0,0.4 -0.588,0.809 -0.38,0.124 -0.951,-0.309 -0.235,-0.324" />
        </svg>
      ))}
    </span>
  );
}

export function CoachMenu({ view }: { view: CoachMenuSnapshot }): ReactElement {
  useLanguage();
  const [dragElo, setDragElo] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "white" | "black">("all");
  const [happy, setHappy] = useState(true); // the coach smiles as a greeting
  useEffect(() => {
    const timer = window.setTimeout(() => setHappy(false), 2500);
    return () => window.clearTimeout(timer);
  }, []);
  const [min, max, step] = view.range;
  const sliderElo = dragElo ?? view.sliderElo;
  const shownElo = dragElo ?? view.elo;
  const openings = view.openings.filter((o) => filter === "all" || o.side === filter);
  useKeys((event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      act("play");
    }
  });
  const release = (): void => {
    if (dragElo === null) return;
    act("elo", { elo: dragElo, final: true });
    setDragElo(null);
  };
  return (
    <div className="screen coach-menu">
      <div className="coach-left">
        <section className="card coach-hello">
          <CoachAvatar expression={happy ? "happy" : "neutral"} size={124} />
          <div className="coach-hello-text">
            <h2>{t("coach.name")}</h2>
            <p className="muted">{t("coach.subtitle")}</p>
            <div className="bubble">{view.greeting}</div>
          </div>
        </section>
        <section className="card coach-setup">
          <h2>{t("coach.setup_title")}</h2>
          <span className="field-label">{t("coach.strength")}</span>
          <div className="elo-row">
            <span className={`elo-value${view.adaptive ? " adaptive" : ""}`}>{shownElo}</span>
            <span className="elo-level">{t(view.level)}</span>
          </div>
          <div className={`elo-slider${view.adaptive ? " locked" : ""}`}>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={sliderElo}
              aria-label={t("coach.strength")}
              style={{ "--value": (sliderElo - min) / (max - min) } as React.CSSProperties}
              onChange={(e) => {
                const value = Number(e.target.value);
                setDragElo(value);
                act("elo", { elo: value, final: false });
              }}
              onPointerUp={release}
              onKeyUp={release}
            />
            <div className="elo-range">
              <span>{min}</span>
              <span>{max}</span>
            </div>
          </div>
          <button
            type="button"
            className={`btn pill level-button${view.levelActive ? " active" : ""}`}
            disabled={!view.levelEnabled}
            onClick={() => act("level")}
          >
            {view.levelLabel}
          </button>
          <p className="level-note">{view.note}</p>
          <Segmented
            accent="accent"
            options={(["white", "random", "black"] as const).map((color) => ({ value: color, label: t(`coach.color.${color}`) }))}
            value={view.color}
            onChange={(color) => act("color", { color })}
          />
          <div className="setup-buttons">
            {view.inProgress && (
              <button type="button" className="btn btn-violet big" onClick={() => act("resume")}>
                {t("coach.resume")}
              </button>
            )}
            <button type="button" className="btn btn-primary big" onClick={() => act("play")}>
              {t("coach.play")}
            </button>
          </div>
        </section>
      </div>
      <section className="card openings">
        <header className="openings-head">
          <h2>{t("coach.openings_title")}</h2>
          <Segmented
            options={(["all", "white", "black"] as const).map((value) => ({ value, label: t(`coach.filter.${value}`) }))}
            value={filter}
            onChange={setFilter}
          />
        </header>
        <p className="muted small">{t("coach.openings_desc")}</p>
        <div className="openings-list">
          {openings.map((opening) => (
            <button key={opening.id} type="button" className="opening-row" onClick={() => act("learn", { id: opening.id })}>
              <span className={`side-dot big ${opening.side}`} />
              <span className="opening-text">
                <span className="opening-name">{t(`opening.${opening.id}.name`)}</span>
                <span className="opening-line">
                  {opening.eco} · {opening.line}
                </span>
                <span className="opening-desc">{t(`opening.${opening.id}.desc`)}</span>
              </span>
              <Stars count={opening.stars} />
            </button>
          ))}
        </div>
      </section>
      {view.confirm && <ConfirmDialog text={view.confirm.text} yes={view.confirm.yes} onYes={() => act("confirm_yes")} onNo={() => act("confirm_no")} />}
    </div>
  );
}
