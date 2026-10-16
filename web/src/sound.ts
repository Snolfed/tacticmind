// Sounds synthesised in code on Web Audio — no recording files. They are modelled on real wooden ones: a short pulse
// (how long the felt base or a mallet touches the wood decides how bright it sounds) rings a bank of resonators tuned
// to the modes of a wooden board, a wooden piece or a marimba bar, each with its own damping.
//  - move: a soft, round "thock" of a felted piece on the board; capture: a crisp "clack" of wood on wood, then the thock,
//  - check: a thock and a marimba note; castling: two thocks; promotion: a thock and two rising marimba notes,
//  - success and brilliant move: marimba arpeggios (brilliant ends on a glockenspiel sparkle), mistake: two low notes.

type Samples = Float32Array;
/** A mode of a resonating body: frequency (Hz), quality factor (higher rings longer) and level. */
type Mode = [number, number, number];

/** A wooden board under a felted piece: a low body, warm mids and a little top (lowest modes damp slowest). */
const BOARD: Mode[] = [
  [168, 12, 0.22],
  [292, 14, 0.38],
  [447, 18, 0.62],
  [618, 24, 0.85],
  [836, 28, 1.0],
  [1094, 30, 0.9],
  [1475, 40, 1.0],
  [2040, 44, 0.9],
  [2780, 46, 0.5],
];
/** A wooden piece knocked by another one: higher, brighter modes. */
const PIECE: Mode[] = [
  [930, 24, 0.55],
  [1610, 28, 1.0],
  [2330, 32, 0.8],
  [3240, 36, 0.45],
  [4350, 40, 0.2],
];

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

  /** The force of an impact: a half-sine lasting ``contact`` seconds with a touch of grain. */
  private pulse(contact: number, grain: number): Samples {
    const n = Math.max(2, Math.round(contact * this.rate));
    const pulse = new Float32Array(n);
    for (let i = 0; i < n; i++) pulse[i] = Math.sin((Math.PI * (i + 0.5)) / n) * (1 + grain * this.random());
    return pulse;
  }

  /** Rings each mode (a two-pole resonator) with the pulse and adds the result to ``out`` from ``start`` seconds. */
  private ring(out: Samples, start: number, pulse: Samples, modes: Mode[], gain: number, pitch = 1): void {
    const begin = Math.floor(start * this.rate);
    for (const [base, q, level] of modes) {
      const freq = base * pitch;
      if (freq >= this.rate / 2.2) continue;
      const w = (2 * Math.PI * freq) / this.rate;
      const r = Math.exp(-w / (2 * q));
      const a1 = 2 * r * Math.cos(w);
      const a2 = -r * r;
      const scale = gain * level * Math.sin(w); // unit-amplitude ringing for a unit impulse
      const length = Math.min(out.length - begin, Math.ceil(Math.log(1e-4) / Math.log(r)));
      let y1 = 0;
      let y2 = 0;
      for (let i = 0; i < length; i++) {
        const y = a1 * y1 + a2 * y2 + (pulse[i] ?? 0);
        y2 = y1;
        y1 = y;
        out[begin + i] = (out[begin + i] ?? 0) + scale * y;
      }
    }
  }

  /** A felted piece set down on the board. */
  thock(out: Samples, start: number, gain = 1, pitch = 1): void {
    this.ring(out, start, this.pulse(0.00045, 0.15), BOARD, gain, pitch);
  }

  /** Wood knocking on wood: a short contact, so the piece's high modes speak. */
  clack(out: Samples, start: number, gain = 1, pitch = 1): void {
    this.ring(out, start, this.pulse(0.00025, 0.3), PIECE, gain, pitch);
  }

  /** A marimba bar struck with a soft mallet: fundamental, the tuned 4th partial and a faint 10th. */
  marimba(out: Samples, start: number, freq: number, gain = 1, ring = 0.45): void {
    const modes: Mode[] = [
      [freq, Math.PI * freq * ring, 1],
      [freq * 3.98, Math.PI * freq * 3.98 * ring * 0.22, 0.28],
      [freq * 9.9, Math.PI * freq * 9.9 * ring * 0.06, 0.08],
    ];
    this.ring(out, start, this.pulse(0.0016, 0.05), modes, gain);
  }

  /** A glockenspiel bar: bright and long, for the sparkle of a brilliant move. */
  glock(out: Samples, start: number, freq: number, gain = 1): void {
    const modes: Mode[] = [
      [freq, Math.PI * freq * 0.7, 1],
      [freq * 2.76, Math.PI * freq * 2.76 * 0.25, 0.35],
      [freq * 5.4, Math.PI * freq * 5.4 * 0.08, 0.15],
    ];
    this.ring(out, start, this.pulse(0.0006, 0.05), modes, gain);
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

/** Peak level, low-pass cutoff (Hz) and echo (a small wooden room) of each sound. */
const FINISH: Record<string, [number, number, number]> = {
  move: [0.55, 7000, 0.05],
  capture: [0.62, 9000, 0.05],
  check: [0.55, 8000, 0.06],
  castle: [0.55, 7000, 0.05],
  promote: [0.55, 8000, 0.06],
  success: [0.45, 8000, 0.08],
  brilliant: [0.48, 9000, 0.1],
  error: [0.42, 4000, 0.06],
};

export function buildSounds(rate: number): Record<string, Samples> {
  const s = new Synth(rate);
  const move = s.buffer(0.14);
  s.thock(move, 0);
  const capture = s.buffer(0.16);
  s.clack(capture, 0, 3);
  s.thock(capture, 0.012, 1, 1.06);
  const check = s.buffer(0.5);
  s.thock(check, 0, 1, 1.03);
  s.marimba(check, 0.012, 1318.5, 0.5, 0.25); // E6
  const castle = s.buffer(0.24);
  s.thock(castle, 0, 0.85, 0.94);
  s.thock(castle, 0.085, 1, 1.05);
  const promote = s.buffer(0.55);
  s.thock(promote, 0);
  s.marimba(promote, 0.06, 784, 0.55, 0.3); // G5
  s.marimba(promote, 0.14, 1046.5, 0.65, 0.35); // C6
  const success = s.buffer(0.9);
  s.marimba(success, 0, 784, 0.7, 0.35); // G5
  s.marimba(success, 0.09, 1046.5, 0.85, 0.45); // C6
  const brilliant = s.buffer(1.2);
  [523.25, 659.25, 784, 1046.5, 1318.5].forEach((freq, i) => s.marimba(brilliant, 0.055 * i, freq, 0.55 + 0.08 * i, 0.4));
  s.glock(brilliant, 0.3, 2093, 0.3); // C7
  const error = s.buffer(0.42);
  s.marimba(error, 0, 220, 0.9, 0.18); // A3
  s.marimba(error, 0.11, 174.6, 1, 0.22); // F3
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
