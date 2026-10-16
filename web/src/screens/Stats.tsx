// Statystyki: kafelki z liczbami, ranking w czasie i skuteczność w motywach.

import type { ReactElement } from "react";
import { go, screenAction } from "../api";
import { BarChart, LineChart } from "../components/Charts";
import { ConfirmDialog, Segmented } from "../components/Widgets";
import { t, useLanguage } from "../i18n";
import type { StatsSnapshot } from "../types";

const act = (name: string, data: Record<string, unknown> = {}): void => screenAction("stats", name, data);

export function Stats({ view }: { view: StatsSnapshot }): ReactElement {
  useLanguage();
  return (
    <div className="screen stats">
      <header className="stats-head">
        <h1>{t("stats.title")}</h1>
        <span className="muted">{t("stats.system")}</span>
        <Segmented
          options={[
            { value: "glicko", label: "Glicko-2" },
            { value: "elo", label: "Elo" },
          ]}
          value={view.system}
          onChange={(system) => act("system", { system })}
        />
      </header>
      <div className="stat-cards">
        {view.cards.map((card) => (
          <div key={card.label} className={`card stat-card accent-${card.accent}`}>
            <span className="stat-label">{card.label}</span>
            <span className="stat-value">{card.value}</span>
          </div>
        ))}
      </div>
      <div className="stats-charts">
        <section className="chart-block rating-chart">
          <h2>
            {t("stats.rating_chart")}
            {view.band && <small>{t("stats.band_note")}</small>}
          </h2>
          <div className="card chart-card">
            <LineChart values={view.ratings} band={view.band} />
          </div>
        </section>
        <section className="chart-block">
          <h2>{t("stats.themes_chart")}</h2>
          <div className="card chart-card">
            <BarChart items={view.themes} />
          </div>
        </section>
      </div>
      <footer className="stats-foot">
        <button type="button" className="btn btn-primary" onClick={() => go("play")}>
          {t("stats.play")}
        </button>
        <button type="button" className="btn btn-danger" onClick={() => act("reset")}>
          {t("stats.reset")}
        </button>
      </footer>
      {view.confirm && (
        <ConfirmDialog title={t("stats.reset_title")} text={t("stats.reset_body")} yes={t("stats.reset_yes")} onYes={() => act("confirm_yes")} onNo={() => act("confirm_no")} />
      )}
    </div>
  );
}
