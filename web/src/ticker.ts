// Shared animation loop (requestAnimationFrame) with a frame limit and an FPS counter.
// Animations drawn in JS (pieces, effects, evaluation bar) get their time from this loop,
// so the FPS limit from the settings applies to all of them at once.

import { useEffect, useRef } from "react";

type Callback = (now: number, dt: number) => void;

const callbacks = new Set<Callback>();
let limit = 0; // 0 = unlimited (display refresh rate)
let last = 0;
let running = false;
const frames: number[] = [];
let frameMs = 0;

export function setFpsLimit(value: number): void {
  limit = value;
}

/** Frames per second over the last second and the average frame time (ms). */
export function fpsStats(): { fps: number; ms: number } {
  const now = performance.now();
  while (frames.length && (frames[0] ?? 0) < now - 1000) frames.shift();
  return { fps: frames.length, ms: frameMs };
}

function loop(now: number): void {
  requestAnimationFrame(loop);
  const minGap = limit > 0 ? 1000 / limit : 0;
  // 1 ms tolerance: with a limit equal to the display refresh rate we do not drop frames due to small clock jitter.
  if (minGap && now - last < minGap - 1) return;
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 60;
  if (minGap && last && now - last < 2 * minGap) {
    last += Math.max(1, Math.floor((now - last + 1) / minGap)) * minGap; // even spacing, no drift
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

/** Hook: calls the function every frame (with the latest version of the function, without resubscribing). */
export function useFrame(callback: Callback, active = true): void {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    if (!active) return;
    return subscribe((now, dt) => ref.current(now, dt));
  }, [active]);
}
