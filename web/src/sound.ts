// Dźwięki syntezowane w kodzie (port ui/sounds.py na Web Audio) — bez plików z nagraniami.
//  - ruch: drewniane „puknięcie”, bicie: podwójne „klaśnięcie”, szach: puknięcie z dzwoneczkiem,
//  - roszada: dwa puknięcia, promocja: rosnący ton, sukces / genialny ruch: dzwonkowe arpeggio,
//  - błąd: miękkie, opadające „bonk”.
// Na końcu filtr dolnoprzepustowy i delikatne echo — brzmi miękko, nie „bije po uszach”.

type Samples = Float32Array;

class Synth {
  private seed = 1234;
  constructor(readonly rate: number) {}

  private random(): number {
    // Prosty generator liniowy — szum uderzenia ma być powtarzalny, nie kryptograficzny.
    this.seed = (this.seed * 1664525 + 1013904223) % 4294967296;
    return (this.seed / 4294967296) * 2 - 1;
  }

  buffer(seconds: number): Samples {
    return new Float32Array(Math.floor(this.rate * seconds));
  }

  knock(out: Samples, start: number, gain = 1, brightness = 1): void {
    const rate = this.rate;
    const modes: [number, number, number][] = [
      [140, 30, 0.7],
      [290, 42, 1.0],
      [560, 65, 0.45],
      [980 * brightness, 95, 0.15],
    ];
    const begin = Math.floor(start * rate);
    const length = Math.min(out.length - begin, Math.floor(0.15 * rate));
    let lowpass = 0;
    const alpha = Math.min(0.5, 0.1 * brightness);
    for (let i = 0; i < length; i++) {
      const t = i / rate;
      const drop = 1 + 0.05 * Math.exp(-t * 70);
      let value = 0;
      for (const [freq, decay, amp] of modes) value += amp * Math.exp(-t * decay) * Math.sin(2 * Math.PI * freq * drop * t);
      lowpass += alpha * (this.random() - lowpass);
      value += 0.5 * lowpass * Math.exp(-t * 320);
      const attack = Math.min(1, i / (0.0025 * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * attack * value;
    }
  }

  bell(out: Samples, start: number, freq: number, gain = 1, decay = 5, length = 0.6): void {
    const rate = this.rate;
    const partials: [number, number, number][] = [
      [1, 1, 1],
      [2, 0.2, 1.8],
      [3, 0.06, 2.6],
    ];
    const begin = Math.floor(start * rate);
    const count = Math.min(out.length - begin, Math.floor(length * rate));
    for (let i = 0; i < count; i++) {
      const t = i / rate;
      let value = 0;
      for (const [ratio, amp, speed] of partials) value += amp * Math.exp(-t * decay * speed) * Math.sin(2 * Math.PI * freq * ratio * t);
      const attack = Math.min(1, i / (0.01 * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * attack * value;
    }
  }

  tone(out: Samples, start: number, f0: number, f1: number, length: number, gain: number, decay: number): void {
    const rate = this.rate;
    const begin = Math.floor(start * rate);
    const count = Math.min(out.length - begin, Math.floor(length * rate));
    let phase = 0;
    for (let i = 0; i < count; i++) {
      const t = i / rate;
      const freq = f0 + (f1 - f0) * (i / Math.max(1, count - 1));
      phase += (2 * Math.PI * freq) / rate;
      const env = Math.exp(-t * decay) * Math.min(1, i / (0.006 * rate));
      out[begin + i] = (out[begin + i] ?? 0) + gain * env * (Math.sin(phase) + 0.1 * Math.sin(2 * phase));
    }
  }
}

function soften(samples: Samples, rate: number, cutoff = 2600, echo = 0.12): Samples {
  const alpha = 1 - Math.exp((-2 * Math.PI * cutoff) / rate);
  const out = new Float32Array(samples.length);
  let state = 0;
  for (let i = 0; i < samples.length; i++) {
    state += alpha * ((samples[i] ?? 0) - state);
    out[i] = state;
  }
  const delay = Math.floor(0.019 * rate);
  for (let i = out.length - 1; i >= delay; i--) out[i] = (out[i] ?? 0) + echo * (out[i - delay] ?? 0);
  return out;
}

/** Normalizacja do zadanego poziomu i łagodne wyciszenie końcówki. */
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

const LEVELS: Record<string, number> = {
  move: 0.45,
  capture: 0.52,
  check: 0.45,
  castle: 0.45,
  promote: 0.45,
  success: 0.42,
  brilliant: 0.45,
  error: 0.32,
};

export function buildSounds(rate: number): Record<string, Samples> {
  const s = new Synth(rate);
  const move = s.buffer(0.18);
  s.knock(move, 0, 1, 1);
  const capture = s.buffer(0.22);
  s.knock(capture, 0, 1, 1.25);
  s.knock(capture, 0.03, 0.7, 1.1);
  const check = s.buffer(0.5);
  s.knock(check, 0, 1, 1);
  s.bell(check, 0.015, 880, 0.32, 6, 0.48);
  const castle = s.buffer(0.28);
  s.knock(castle, 0, 0.95, 1);
  s.knock(castle, 0.09, 0.8, 0.9);
  const promote = s.buffer(0.42);
  s.knock(promote, 0, 1, 1);
  s.tone(promote, 0.03, 523, 784, 0.32, 0.25, 7);
  const success = s.buffer(1.2);
  [523.25, 659.25, 783.99, 1046.5].forEach((freq, i) => s.bell(success, 0.085 * i, freq, i < 3 ? 0.5 : 0.6, 3.5, 1.2 - 0.085 * i));
  const brilliant = s.buffer(1.3);
  [659.25, 783.99, 987.77, 1318.5].forEach((freq, i) => s.bell(brilliant, 0.065 * i, freq, 0.5, 3.2, 1.3 - 0.065 * i));
  s.bell(brilliant, 0.27, 1975.5, 0.12, 2.5, 1.0);
  const error = s.buffer(0.45);
  s.tone(error, 0, 294, 277, 0.18, 0.7, 12);
  s.tone(error, 0.13, 220, 208, 0.3, 0.7, 9);
  const raw: Record<string, Samples> = { move, capture, check, castle, promote, success, brilliant, error };
  const result: Record<string, Samples> = {};
  for (const [name, samples] of Object.entries(raw)) result[name] = normalize(soften(samples, rate), LEVELS[name] ?? 0.4);
  return result;
}

class SoundPlayer {
  private context: AudioContext | null = null;
  private buffers: Record<string, AudioBuffer> = {};
  private gain: GainNode | null = null;
  enabled = true;
  volume = 0.7;

  /** Kontekst audio tworzymy przy pierwszym kliknięciu (przeglądarki blokują dźwięk przed interakcją). */
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
    // Krzywa kwadratowa — suwak zmienia głośność „naturalnie” dla ucha.
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
