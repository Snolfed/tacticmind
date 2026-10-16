import { describe, expect, it } from "vitest";
import { buildSounds } from "./sound";

describe("sounds", () => {
  const rate = 48000;
  const sounds = buildSounds(rate);

  it("builds every sound the game plays, clean and within range", () => {
    expect(Object.keys(sounds).sort()).toEqual(["brilliant", "capture", "castle", "check", "error", "move", "promote", "success"]);
    for (const samples of Object.values(sounds)) {
      let peak = 0;
      for (const x of samples) {
        expect(Number.isFinite(x)).toBe(true);
        peak = Math.max(peak, Math.abs(x));
      }
      expect(peak).toBeGreaterThan(0.2);
      expect(peak).toBeLessThanOrEqual(1);
    }
  });

  it("a move is a short, crisp tock", () => {
    const move = sounds.move as Float32Array;
    expect(move.length / rate).toBeLessThan(0.2);
    // Most of the energy is in the first 40 ms: the sound does not ring on.
    let head = 0;
    let all = 0;
    move.forEach((x, i) => {
      all += x * x;
      if (i < 0.04 * rate) head += x * x;
    });
    expect(head / all).toBeGreaterThan(0.9);
  });
});
