// Full-window effects: confetti after solving a puzzle and expanding rings.
// A single canvas over the interface, drawn only while something is happening.

import { subscribe } from "./ticker";

type Rgb = [number, number, number];

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  color: Rgb;
  size: number;
  angle: number;
  spin: number;
}

interface Ring {
  x: number;
  y: number;
  age: number;
  duration: number;
  radius: number;
  color: Rgb;
}

export const ACCENT: Rgb = [45, 212, 191];
export const VIOLET: Rgb = [167, 139, 250];
export const AMBER: Rgb = [251, 191, 36];
export const ROSE: Rgb = [251, 113, 133];
export const BLUE: Rgb = [96, 165, 250];
export const RED: Rgb = [244, 63, 94];
export const BRILLIANT: Rgb = [34, 211, 238];
export const WHITE: Rgb = [255, 255, 255];
export const CONFETTI: Rgb[] = [ACCENT, VIOLET, AMBER, ROSE, BLUE, WHITE];

class Effects {
  private particles: Particle[] = [];
  private rings: Ring[] = [];
  private canvas: HTMLCanvasElement | null = null;
  private unsubscribe: (() => void) | null = null;

  attach(canvas: HTMLCanvasElement | null): void {
    this.canvas = canvas;
  }

  /** Confetti from a point (window coordinates in CSS pixels); ``scale`` — board size / 640. */
  burst(x: number, y: number, colors: Rgb[], count = 46, scale = 1): void {
    for (let i = 0; i < count; i++) {
      const angle = Math.random() < 0.8 ? -Math.PI * Math.random() : Math.random() * Math.PI * 2;
      const speed = (160 + Math.random() * 360) * scale;
      const life = 0.8 + Math.random() * 0.7;
      this.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life,
        maxLife: life,
        color: colors[Math.floor(Math.random() * colors.length)] ?? WHITE,
        size: (3 + Math.random() * 4) * scale,
        angle: Math.random() * Math.PI * 2,
        spin: -9 + Math.random() * 18,
      });
    }
    this.start();
  }

  ring(x: number, y: number, radius: number, color: Rgb, duration = 0.6): void {
    this.rings.push({ x, y, age: 0, duration, radius, color });
    this.start();
  }

  private start(): void {
    if (!this.unsubscribe) this.unsubscribe = subscribe((_now, dt) => this.frame(dt));
  }

  private frame(dt: number): void {
    const gravity = 900;
    for (const p of this.particles) {
      p.life -= dt;
      p.vy += gravity * dt;
      p.vx *= Math.exp(-1.6 * dt);
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.angle += p.spin * dt;
    }
    this.particles = this.particles.filter((p) => p.life > 0);
    for (const r of this.rings) r.age += dt;
    this.rings = this.rings.filter((r) => r.age < r.duration);
    this.draw();
    if (!this.particles.length && !this.rings.length) {
      this.unsubscribe?.();
      this.unsubscribe = null;
    }
  }

  private draw(): void {
    const canvas = this.canvas;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const r of this.rings) {
      const t = r.age / r.duration;
      const radius = r.radius * (0.6 + 0.9 * (1 - (1 - t) ** 3));
      ctx.strokeStyle = `rgba(${r.color.join(",")},${(0.8 * (1 - t)).toFixed(3)})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(r.x, r.y, radius, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (const p of this.particles) {
      const alpha = Math.min(1, p.life / (p.maxLife * 0.5));
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);
      ctx.fillStyle = `rgba(${p.color.join(",")},${alpha.toFixed(3)})`;
      ctx.fillRect(-p.size, -p.size * 0.55, p.size * 2, p.size * 1.1);
      ctx.restore();
    }
  }
}

export const effects = new Effects();
