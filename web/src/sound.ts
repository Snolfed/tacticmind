// Sounds synthesised in code on Web Audio — no recording files. The character follows the familiar online-chess set:
//  - move: a short, bright wooden "tock" (a click of the piece and a hollow board), capture: a sharper double "clack",
//  - check: a tock with a small high ring, castling: two quick tocks, promotion: a tock and a rising "shing",
//  - success: a bright two-note chime, brilliant move: a sparkling arpeggio, mistake: a low, short "bwomp".
// Board sounds stay dry (no echo) and keep their highs: crisp, not muffled.

type Samples = Float32Array;

class Synth {
  private seed = 1234;
  constructor(readonly rate: number) {}

  private random(): number {
    // A simple linear generator — the hit noise should be repeatable, not cryptographic.
    this.seed = (this.seed * 1664525 + 1013904223) % 4294967296;
    return (this.seed / 4294967296) * 2 - 1;
  }

  buffer(seconds: number): Samples {
    return new Float32Array(Math.floor(this.rate * seconds));
  }

  /** A piece set down on a wooden board: a sharp click of filtered noise and a short, hollow wooden body.
   *  ``pitch`` scales the body's modes, ``click`` the loudness of the click. */
  tock(out: Samples, start: number, gain = 1, pitch = 1, click = 1): void {
    const rate = this.rate;
    const modes: [number, number, number][] = [
      [210, 45, 0.3], // the board's thump
      [880 * pitch, 55, 0.75],
      [1520 * pitch, 72, 1.0],
      [2450 * pitch, 105, 0.6],
      [3800 * pitch, 150, 0.3],
    ];
    const begin = Math.floor(start * rate);
    const length = Math.min(out.length - begin, Math.floor(0.12 * rate));
    let low = 0;
    for (let i = 0; i < length; i++) {
      const t = i / rate;
      const sag = 1 + 0.04 * Math.exp(-t * 90); // the wood "gives" for a moment: modes start slightly higher
      let value = 0;
      for (const [freq, decay, amp] of modes) value += amp * Math.exp(-t * decay) * Math.sin(2 * Math.PI * freq * sag * t);
      const noise = this.random();
      low += 0.25 * (noise - low);
      value += click * 1.8 * (noise - low) * Math.exp(-t * 450); // high-passed noise: the click
      const attack = Math.min(1, i / (0.0008 * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * attack * value;
    }
  }

  bell(out: Samples, start: number, freq: number, gain = 1, decay = 5, length = 0.6): void {
    const rate = this.rate;
    const partials: [number, number, number][] = [
      [1, 1, 1],
      [2, 0.25, 1.8],
      [3, 0.08, 2.6],
      [4.2, 0.04, 3.4], // a slightly inharmonic shimmer
    ];
    const begin = Math.floor(start * rate);
    const count = Math.min(out.length - begin, Math.floor(length * rate));
    for (let i = 0; i < count; i++) {
      const t = i / rate;
      let value = 0;
      for (const [ratio, amp, speed] of partials) value += amp * Math.exp(-t * decay * speed) * Math.sin(2 * Math.PI * freq * ratio * t);
      const attack = Math.min(1, i / (0.004 * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * attack * value;
    }
  }

  tone(out: Samples, start: number, f0: number, f1: number, length: number, gain: number, decay: number, attackTime = 0.006): void {
    const rate = this.rate;
    const begin = Math.floor(start * rate);
    const count = Math.min(out.length - begin, Math.floor(length * rate));
    let phase = 0;
    for (let i = 0; i < count; i++) {
      const t = i / rate;
      const freq = f0 + (f1 - f0) * (i / Math.max(1, count - 1));
      phase += (2 * Math.PI * freq) / rate;
      const env = Math.exp(-t * decay) * Math.min(1, i / (attackTime * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * env * (Math.sin(phase) + 0.15 * Math.sin(2 * phase));
    }
  }

  /** Noise swept upwards through a resonant band: the "shing" of a promotion. */
  sweep(out: Samples, start: number, f0: number, f1: number, length: number, gain: number): void {
    const rate = this.rate;
    const begin = Math.floor(start * rate);
    const count = Math.min(out.length - begin, Math.floor(length * rate));
    let low = 0;
    let band = 0;
    for (let i = 0; i < count; i++) {
      const p = i / Math.max(1, count - 1);
      const freq = f0 * (f1 / f0) ** p;
      const f = 2 * Math.sin((Math.PI * freq) / rate); // state-variable filter, Q ≈ 4
      const high = this.random() - low - 0.25 * band;
      band += f * high;
      low += f * band;
      const env = Math.sin(Math.PI * p) ** 2;
      out[begin + i] = (out[begin + i] ?? 0) + gain * env * band;
    }
  }
}

/** A gentle low-pass (``cutoff``) and an optional short room echo. */
function polish(samples: Samples, rate: number, cutoff: number, echo: number): Samples {
  const alpha = 1 - Math.exp((-2 * Math.PI * cutoff) / rate);
  const out = new Float32Array(samples.length);
  let state = 0;
  for (let i = 0; i < samples.length; i++) {
    state += alpha * ((samples[i] ?? 0) - state);
    out[i] = state;
  }
  if (echo > 0) {
    const delay = Math.floor(0.023 * rate);
    for (let i = out.length - 1; i >= delay; i--) out[i] = (out[i] ?? 0) + echo * (out[i - delay] ?? 0);
  }
  return out;
}

/** Normalisation to the given level and a gentle fade-out of the tail. */
function normalize(samples: Samples, peak: number): Samples {
  let top = 0;
  for (const x of samples) top = Math.max(top, Math.abs(x));
  const scale = peak / (top || 1);
  const fade = Math.min(samples.length, 220);
  for (let i = 0; i < samples.length; i++) {
    let x = (samples[i] ?? 0) * scale;
    if (i >= samples.length - fade) x *= (samples.length - i) / fade;
    samples[i] = Math.max(-1, Math.min(1, x));
  }
  return samples;
}

/** Peak level, low-pass cutoff (Hz) and echo of each sound. */
const FINISH: Record<string, [number, number, number]> = {
  move: [0.5, 9000, 0],
  capture: [0.6, 10000, 0],
  check: [0.52, 9000, 0.04],
  castle: [0.5, 9000, 0],
  promote: [0.5, 9000, 0.05],
  success: [0.42, 7000, 0.1],
  brilliant: [0.45, 8000, 0.12],
  error: [0.36, 2500, 0.06],
};

export function buildSounds(rate: number): Record<string, Samples> {
  const s = new Synth(rate);
  const move = s.buffer(0.13);
  s.tock(move, 0);
  const capture = s.buffer(0.16);
  s.tock(capture, 0, 1, 1.15, 1.8);
  s.tock(capture, 0.016, 0.7, 1.4, 1.3);
  const check = s.buffer(0.42);
  s.tock(check, 0, 1, 1.08, 1.2);
  s.bell(check, 0.008, 1568, 0.22, 9, 0.4);
  const castle = s.buffer(0.21);
  s.tock(castle, 0, 0.9, 0.95);
  s.tock(castle, 0.075, 1, 1.05);
  const promote = s.buffer(0.42);
  s.tock(promote, 0);
  s.sweep(promote, 0.03, 1500, 6500, 0.24, 0.5);
  s.bell(promote, 0.2, 1318.5, 0.22, 7, 0.22);
  const success = s.buffer(0.9);
  s.bell(success, 0, 1046.5, 0.55, 5, 0.6);
  s.bell(success, 0.1, 1568, 0.6, 4, 0.8);
  const brilliant = s.buffer(1.1);
  [1046.5, 1318.5, 1568, 2093].forEach((freq, i) => s.bell(brilliant, 0.055 * i, freq, i < 3 ? 0.45 : 0.55, 3.6, 1.1 - 0.055 * i));
  s.sweep(brilliant, 0.18, 3000, 9000, 0.35, 0.18);
  const error = s.buffer(0.38);
  s.tone(error, 0, 233, 174, 0.3, 0.8, 9, 0.012);
  s.tone(error, 0, 116.5, 87, 0.3, 0.35, 9, 0.012);
  const raw: Record<string, Samples> = { move, capture, check, castle, promote, success, brilliant, error };
  const result: Record<string, Samples> = {};
  for (const [name, samples] of Object.entries(raw)) {
    const [peak, cutoff, echo] = FINISH[name] ?? [0.4, 8000, 0];
    result[name] = normalize(polish(samples, rate, cutoff, echo), peak);
  }
  return result;
}

class SoundPlayer {
  private context: AudioContext | null = null;
  private buffers: Record<string, AudioBuffer> = {};
  private gain: GainNode | null = null;
  enabled = true;
  volume = 0.7;

  /** The audio context is created on the first click (browsers block sound before interaction). */
  unlock(): void {
    if (this.context) {
      if (this.context.state === "suspended") void this.context.resume();
      return;
    }
    try {
      const context = new AudioContext({ latencyHint: "interactive" });
      this.context = context;
      this.gain = context.createGain();
      this.gain.connect(context.destination);
      this.applyVolume();
      for (const [name, samples] of Object.entries(buildSounds(context.sampleRate))) {
        const buffer = context.createBuffer(1, samples.length, context.sampleRate);
        buffer.copyToChannel(samples as Float32Array<ArrayBuffer>, 0);
        this.buffers[name] = buffer;
      }
    } catch {
      this.context = null;
    }
  }

  setVolume(enabled: boolean, volume: number): void {
    this.enabled = enabled;
    this.volume = volume;
    this.applyVolume();
  }

  private applyVolume(): void {
    // Quadratic curve — the slider changes volume "naturally" for the ear.
    if (this.gain) this.gain.gain.value = this.volume ** 2;
  }

  play(name: string): void {
    const context = this.context;
    const buffer = this.buffers[name];
    if (!context || !buffer || !this.gain || !this.enabled || this.volume <= 0.02) return;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    source.start();
  }
}

export const sounds = new SoundPlayer();
