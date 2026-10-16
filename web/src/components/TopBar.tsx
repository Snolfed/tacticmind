// Top bar: logo, navigation, language, sound, settings (FPS counter, frame limit), full screen
// and a large rating with an animated change, plus the streak with a flame.

import { useEffect, useLayoutEffect, useRef, useState, type ReactElement } from "react";
import { go, send } from "../api";
import { languages, t, useLanguage } from "../i18n";
import { sounds } from "../sound";
import { useFrame } from "../ticker";
import type { ScreenName, TopBarSnapshot, UiSettings } from "../types";
import { IconFlame, IconFullscreen, IconFullscreenExit, IconSettings, IconSoundOff, IconSoundOn } from "./Icons";
import { Segmented } from "./Widgets";

const NAV: { screen: ScreenName; key: string; active: ScreenName[] }[] = [
  { screen: "play", key: "nav.play", active: ["play"] },
  { screen: "coach", key: "nav.coach", active: ["coach", "coach_game"] },
  { screen: "stats", key: "nav.stats", active: ["stats"] },
  { screen: "howto", key: "nav.howto", active: ["howto"] },
];

export const FPS_LIMITS = [60, 120, 144, 170, 240, 0];

// In the Tauri window, full screen is toggled by the window itself: with requestFullscreen WebView2 (Windows)
// only enlarges the page to the window size. Permission for these two commands comes from web/src-tauri/capabilities.
interface TauriInternals {
  invoke(cmd: string, args?: Record<string, unknown>): Promise<unknown>;
}
const tauri = (window as unknown as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
const FULLSCREEN_EVENT = "tacticmind:fullscreen";

async function windowIsFullscreen(api: TauriInternals): Promise<boolean> {
  return (await api.invoke("plugin:window|is_fullscreen", { label: "main" })) === true;
}

export function toggleFullscreen(): void {
  if (tauri) {
    const api = tauri;
    void (async () => {
      try {
        await api.invoke("plugin:window|set_fullscreen", { label: "main", value: !(await windowIsFullscreen(api)) });
      } catch {
        // without the permission a regular window remains
      }
      window.dispatchEvent(new Event(FULLSCREEN_EVENT));
    })();
    return;
  }
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
  else void document.documentElement.requestFullscreen?.().catch(() => undefined);
}

export function useFullscreen(): boolean {
  const [full, setFull] = useState(() => !!document.fullscreenElement);
  useEffect(() => {
    if (tauri) {
      const api = tauri;
      let alive = true;
      const check = (): void => {
        windowIsFullscreen(api).then(
          (value) => alive && setFull(value),
          () => undefined,
        );
      };
      check();
      window.addEventListener("resize", check);
      window.addEventListener(FULLSCREEN_EVENT, check);
      return () => {
        alive = false;
        window.removeEventListener("resize", check);
        window.removeEventListener(FULLSCREEN_EVENT, check);
      };
    }
    const onChange = (): void => setFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  return full;
}

export function Logo({ size = 26 }: { size?: number }): ReactElement {
  return (
    <span className="logo" style={{ fontSize: size }}>
      Tactic<span className="logo-mind">Mind</span>
    </span>
  );
}

function Rating({ top }: { top: TopBarSnapshot }): ReactElement {
  const valueRef = useRef<HTMLSpanElement>(null);
  const shown = useRef(top.rating);
  const source = useRef(top.source);
  const [animating, setAnimating] = useState(false);
  const firstSeq = useRef(top.deltaSeq);
  const [bump, setBump] = useState(0);

  useEffect(() => {
    if (source.current !== top.source) {
      source.current = top.source;
      shown.current = top.rating; // a different rating — no number "rolling"
      if (valueRef.current) valueRef.current.textContent = String(top.rating);
      return;
    }
    if (Math.round(shown.current) !== top.rating) setAnimating(true);
  }, [top.rating, top.source]);

  useEffect(() => {
    if (top.deltaSeq !== firstSeq.current) setBump(top.deltaSeq);
  }, [top.deltaSeq]);

  useFrame((_now, dt) => {
    const target = top.rating;
    shown.current += (target - shown.current) * (1 - Math.exp(-5 * dt));
    if (Math.abs(target - shown.current) < 0.5) {
      shown.current = target;
      setAnimating(false);
    }
    if (valueRef.current) valueRef.current.textContent = String(Math.round(shown.current));
  }, animating);

  // We write the number ourselves (also in the frame loop), so React keeps no text in this element.
  useLayoutEffect(() => {
    if (valueRef.current) valueRef.current.textContent = String(Math.round(shown.current));
  });

  const delta = top.delta;
  return (
    <div className="rating">
      <span className="rating-caption">{top.caption}</span>
      <div className="rating-row">
        {bump > 0 && delta !== null && (
          <span key={bump} className={`rating-delta ${delta >= 0 ? "up" : "down"}`}>
            {delta >= 0 ? `+${delta}` : `−${Math.abs(delta)}`}
          </span>
        )}
        <span key={`v${bump}`} ref={valueRef} className={`rating-value${bump > 0 ? " bump" : ""}`} />
        {top.rd !== null && <span className="rating-rd">± {top.rd}</span>}
        {top.streak > 0 && top.source === "puzzles" && (
          <span className="streak" title="Streak">
            <IconFlame size={24} className="flame" />
            {top.streak}
          </span>
        )}
      </div>
    </div>
  );
}

function SettingsMenu({ settings, onClose }: { settings: UiSettings; onClose: () => void }): ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen();
  useEffect(() => {
    const onDown = (event: PointerEvent): void => {
      const target = event.target as Node;
      if (ref.current && !ref.current.contains(target) && !(target as HTMLElement).closest?.(".settings-toggle")) onClose();
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);
  return (
    <div className="settings-menu card" ref={ref} role="dialog">
      <h3>{t("ui.settings")}</h3>
      <label className="switch-row">
        <span>
          {t("ui.fps_counter")}
          <small>{t("ui.fps_counter_hint")}</small>
        </span>
        <input type="checkbox" className="switch" checked={settings.showFps} onChange={(e) => send({ type: "settings", showFps: e.target.checked })} />
      </label>
      <div className="settings-block">
        <span>{t("ui.fps_limit")}</span>
        <Segmented
          className="fps-limits"
          accent="accent"
          options={FPS_LIMITS.map((limit) => ({ value: limit, label: limit === 0 ? "∞" : String(limit), title: limit === 0 ? t("ui.fps_unlimited") : `${limit} FPS` }))}
          value={settings.fpsLimit}
          onChange={(value) => send({ type: "settings", fpsLimit: value })}
        />
        <small>{settings.fpsLimit === 0 ? t("ui.fps_unlimited_hint") : `${settings.fpsLimit} FPS`}</small>
      </div>
      <button type="button" className="btn btn-secondary settings-full" onClick={toggleFullscreen}>
        {fullscreen ? <IconFullscreenExit size={18} /> : <IconFullscreen size={18} />}
        {t("ui.fullscreen")}
      </button>
    </div>
  );
}

export function TopBar({
  screen,
  top,
  lang,
  settings,
}: {
  screen: ScreenName;
  top: TopBarSnapshot;
  lang: string;
  settings: UiSettings;
}): ReactElement {
  useLanguage();
  const [volume, setVolume] = useState<number | null>(null); // value while the slider is being dragged
  const [menu, setMenu] = useState(false);
  const fullscreen = useFullscreen();
  const audible = top.sound && top.volume > 0.02;
  const shownVolume = volume ?? (top.sound ? top.volume : 0);

  return (
    <header className="topbar">
      <button type="button" className="logo-button" onClick={() => go("home")} aria-label="TacticMind">
        <Logo />
      </button>
      <nav className="nav">
        {NAV.map((item) => (
          <button key={item.screen} type="button" className={`nav-item${item.active.includes(screen) ? " active" : ""}`} onClick={() => go(item.screen)}>
            <span className="nav-long">{t(item.key)}</span>
            <span className="nav-short">{item.screen === "howto" ? t("nav.howto_short") : t(item.key)}</span>
          </button>
        ))}
      </nav>
      <div className="controls">
        <Segmented
          className="languages"
          options={languages().map(({ code }) => ({ value: code, label: code.toUpperCase() }))}
          value={lang}
          onChange={(code) => send({ type: "language", code })}
        />
        <button type="button" className="icon-button" onClick={() => send({ type: "sound", toggle: true })} title={audible ? t("sound.on") : t("sound.off")}>
          {audible ? <IconSoundOn /> : <IconSoundOff />}
        </button>
        <input
          className="volume"
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={shownVolume}
          aria-label={t("ui.volume")}
          style={{ "--value": shownVolume } as React.CSSProperties}
          onChange={(e) => {
            const value = Number(e.target.value);
            setVolume(value);
            sounds.setVolume(value > 0.02, value);
            send({ type: "sound", volume: value, final: false });
          }}
          onPointerUp={() => {
            if (volume === null) return;
            send({ type: "sound", volume, final: true });
            setVolume(null);
            sounds.play("move"); // sample: the new volume is audible right away
          }}
          onKeyUp={() => {
            if (volume === null) return;
            send({ type: "sound", volume, final: true });
            setVolume(null);
          }}
        />
        <button type="button" className={`icon-button settings-toggle${menu ? " active" : ""}`} onClick={() => setMenu(!menu)} title={t("ui.settings")}>
          <IconSettings />
        </button>
        <button type="button" className="icon-button fullscreen-button" onClick={toggleFullscreen} title={t("ui.fullscreen")}>
          {fullscreen ? <IconFullscreenExit /> : <IconFullscreen />}
        </button>
        {menu && <SettingsMenu settings={settings} onClose={() => setMenu(false)} />}
      </div>
      <Rating top={top} />
    </header>
  );
}
