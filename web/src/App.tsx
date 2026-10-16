// Main component: top bar, current screen, FPS counter, effects canvas and keyboard handling.

import { useEffect, useRef, useState, type ReactElement } from "react";
import { send, store, useAppState, useOnline } from "./api";
import { toggleFullscreen, TopBar } from "./components/TopBar";
import { effects } from "./effects";
import { loadStrings, setLanguage, t, useLanguage } from "./i18n";
import { CoachGame } from "./screens/CoachGame";
import { CoachMenu } from "./screens/CoachMenu";
import { Home } from "./screens/Home";
import { HowTo } from "./screens/HowTo";
import { Play } from "./screens/Play";
import { Stats } from "./screens/Stats";
import { sounds } from "./sound";
import { fpsStats, setFpsLimit, useFrame } from "./ticker";
import type { AppState, CoachGameSnapshot, CoachMenuSnapshot, HomeSnapshot, HowToSnapshot, PlaySnapshot, StatsSnapshot } from "./types";

function FpsMeter({ limit }: { limit: number }): ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef(0);
  // An empty subscription keeps the frame loop running — the counter shows how many frames the interface really draws.
  useFrame((now) => {
    if (now - last.current < 250 || !ref.current) return;
    last.current = now;
    const { fps, ms } = fpsStats();
    ref.current.textContent = `${fps} FPS · ${ms.toFixed(1)} ms${limit ? ` · limit ${limit}` : ""}`;
  });
  return <div className="fps-meter" ref={ref} />;
}

function Screen({ state }: { state: AppState }): ReactElement {
  switch (state.screen) {
    case "play":
      return <Play view={state.view as PlaySnapshot} />;
    case "coach":
      return <CoachMenu view={state.view as CoachMenuSnapshot} />;
    case "coach_game":
      return <CoachGame view={state.view as CoachGameSnapshot} />;
    case "stats":
      return <Stats view={state.view as StatsSnapshot} />;
    case "howto":
      return <HowTo view={state.view as HowToSnapshot} />;
    default:
      return <Home view={state.view as HomeSnapshot} />;
  }
}

function Connecting(): ReactElement {
  useLanguage();
  return (
    <div className="connecting">
      <div className="spinner" />
      <p>{t("ui.connecting")}</p>
      <small>{t("ui.connecting_detail")}</small>
    </div>
  );
}

export function App(): ReactElement {
  const state = useAppState();
  const online = useOnline();
  const [stringsReady, setStringsReady] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    effects.attach(canvas.current);
    store.start();
    let retry = 0;
    const load = (): void => {
      loadStrings()
        .then(() => setStringsReady(true))
        .catch(() => {
          retry = window.setTimeout(load, 700);
        });
    };
    load();
    // Sound works only after the first interaction with the window (browser policy).
    const unlock = (): void => sounds.unlock();
    window.addEventListener("pointerdown", unlock, { capture: true });
    window.addEventListener("keydown", unlock, { capture: true });
    const offFx = store.onFx((event) => {
      if (event.type === "sound") sounds.play(event.name);
    });
    return () => {
      window.clearTimeout(retry);
      window.removeEventListener("pointerdown", unlock, { capture: true });
      window.removeEventListener("keydown", unlock, { capture: true });
      offFx();
    };
  }, []);

  const lang = state?.lang;
  useEffect(() => {
    if (lang) setLanguage(lang);
  }, [lang, stringsReady]);

  const sound = state?.topbar.sound;
  const volume = state?.topbar.volume;
  useEffect(() => {
    if (sound !== undefined && volume !== undefined) sounds.setVolume(sound, volume);
  }, [sound, volume]);

  const fpsLimit = state?.settings.fpsLimit ?? 0;
  const showFps = state?.settings.showFps ?? false;
  useEffect(() => setFpsLimit(fpsLimit), [fpsLimit]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "F3") {
        event.preventDefault();
        send({ type: "settings", showFps: !showFps });
      } else if (event.key === "F11") {
        event.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showFps]);

  return (
    <div className="app">
      {state && stringsReady ? (
        <>
          <TopBar screen={state.screen} top={state.topbar} lang={state.lang} settings={state.settings} />
          <main className="main" key={state.screen}>
            <Screen state={state} />
          </main>
          {!online && <div className="offline-banner">{t("ui.connecting")}</div>}
          {showFps && <FpsMeter limit={fpsLimit} />}
        </>
      ) : (
        <Connecting />
      )}
      <canvas ref={canvas} className="effects-canvas" aria-hidden="true" />
    </div>
  );
}
