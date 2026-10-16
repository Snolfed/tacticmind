// Ekran startowy: nazwa gry, opis, przyciski i ozdobna szachownica, na której AI pokazuje mata.

import { useEffect, useMemo, useState, type ReactElement } from "react";
import { go } from "../api";
import { Board } from "../components/Board";
import { Logo } from "../components/TopBar";
import { t, useLanguage } from "../i18n";
import type { BoardSnapshot, HomeSnapshot } from "../types";

export function Home({ view }: { view: HomeSnapshot }): ReactElement {
  useLanguage();
  const [thinking, setThinking] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setThinking(true), 600);
    return () => window.clearTimeout(timer);
  }, []);
  const demo = view.demo;
  const board = useMemo<BoardSnapshot>(
    () => ({
      fen: demo.fen,
      seq: 1,
      anim: "none",
      orientation: "white",
      player: "white",
      interactive: false,
      legal: [],
      lastMove: demo.last,
      check: null,
      hint: null,
      arrows: thinking ? [[demo.move.slice(0, 2), demo.move.slice(2, 4), "rgba(45,212,191,0.85)"]] : [],
      feedback: null,
    }),
    [demo.fen, demo.last, demo.move, thinking],
  );
  return (
    <div className="screen home">
      <div className="home-text">
        <h1 className="home-title">
          <Logo size={64} />
        </h1>
        <p className="home-tagline">{t("home.tagline")}</p>
        <p className="home-desc">{t("home.desc")}</p>
        <div className="home-buttons">
          <button type="button" className="btn btn-primary big" onClick={() => go("play")}>
            {t("home.play")}
          </button>
          <button type="button" className="btn btn-violet big" onClick={() => go("coach")}>
            {t("home.coach")}
          </button>
          <div className="home-pair">
            <button type="button" className="btn btn-secondary" onClick={() => go("stats")}>
              {t("home.stats")}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => go("howto")}>
              {t("home.howto")}
            </button>
          </div>
        </div>
        <p className="home-info">{view.info}</p>
        <p className="home-small">{view.source}</p>
        <p className="home-small">{t("home.hint_arrows")}</p>
      </div>
      <div className="home-demo">
        <Board board={board} pulseArrows />
        <div className={`home-tag${thinking ? " shown" : ""}`}>
          <span className="dot-violet" />
          {demo.label}
        </div>
      </div>
    </div>
  );
}
