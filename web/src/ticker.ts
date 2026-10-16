// Wspólna pętla animacji (requestAnimationFrame) z limitem klatek i licznikiem FPS.
// Animacje rysowane w JS (figury, efekty, pasek oceny) dostają czas z tej pętli,
// więc limit FPS z ustawień działa na nie wszystkie naraz.

import { useEffect, useRef } from "react";

type Callback = (now: number, dt: number) => void;

const callbacks = new Set<Callback>();
let limit = 0; // 0 = bez limitu (częstotliwość odświeżania ekranu)
let last = 0;
let running = false;
const frames: number[] = [];
let frameMs = 0;

export function setFpsLimit(value: number): void {
  limit = value;
}

/** Klatki na sekundę z ostatniej sekundy i średni czas klatki (ms). */
export function fpsStats(): { fps: number; ms: number } {
  const now = performance.now();
  while (frames.length && (frames[0] ?? 0) < now - 1000) frames.shift();
  return { fps: frames.length, ms: frameMs };
}

function loop(now: number): void {
  requestAnimationFrame(loop);
  const minGap = limit > 0 ? 1000 / limit : 0;
  // Tolerancja 1 ms: przy limicie równym częstotliwości ekranu nie gubimy klatek przez drobne wahania zegara.
  if (minGap && now - last < minGap - 1) return;
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 60;
  if (minGap && last && now - last < 2 * minGap) {
    last += Math.max(1, Math.floor((now - last + 1) / minGap)) * minGap; // równe odstępy, bez dryfu
  } else {
    last = now;
  }
  frames.push(now);
  const started = performance.now();
  callbacks.forEach((callback) => callback(now, dt));
  frameMs = frameMs * 0.9 + (performance.now() - started) * 0.1;
}

export function subscribe(callback: Callback): () => void {
  callbacks.add(callback);
  if (!running) {
    running = true;
    requestAnimationFrame(loop);
  }
  return () => callbacks.delete(callback);
}

/** Hook: wywołuje funkcję w każdej klatce (z aktualną wersją funkcji, bez ponownej subskrypcji). */
export function useFrame(callback: Callback, active = true): void {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    if (!active) return;
    return subscribe((now, dt) => ref.current(now, dt));
  }, [active]);
}
