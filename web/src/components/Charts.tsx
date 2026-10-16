// SVG charts: a line chart with a gradient under the line (rating over time) and a bar chart (accuracy per theme).

import { useEffect, useId, useRef, useState, type ReactElement } from "react";
import { t } from "../i18n";

export function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, { width: number; height: number }] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((old) => (Math.abs(old.width - width) < 0.5 && Math.abs(old.height - height) < 0.5 ? old : { width, height }));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

export function niceStep(span: number, ticks = 4): number {
  const raw = span / Math.max(1, ticks);
  const magnitude = raw > 0 ? 10 ** Math.floor(Math.log10(raw)) : 1;
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * magnitude) return m * magnitude;
  return 10 * magnitude;
}

export function LineChart({ values, band }: { values: number[]; band: number[] | null }): ReactElement {
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const id = useId().replace(/:/g, "");
  if (values.length < 2) {
    return (
      <div className="chart empty" ref={ref}>
        {t("charts.no_data")}
      </div>
    );
  }
  const plot = { x: 54, y: 16, w: Math.max(10, width - 70), h: Math.max(10, height - 44) };
  const lows = values.map((v, i) => v - (band?.[i] ?? 0));
  const highs = values.map((v, i) => v + (band?.[i] ?? 0));
  let lo = Math.min(...lows);
  let hi = Math.max(...highs);
  if (hi - lo < 40) {
    const mid = (hi + lo) / 2;
    lo = mid - 20;
    hi = mid + 20;
  }
  const step = niceStep(hi - lo);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const px = (i: number): number => plot.x + (plot.w * i) / (values.length - 1);
  const py = (v: number): number => plot.y + plot.h - (plot.h * (v - lo)) / (hi - lo);
  const grid: ReactElement[] = [];
  for (let value = lo; value <= hi + 1e-6; value += step) {
    const y = py(value);
    grid.push(
      <g key={value}>
        <line x1={plot.x} x2={plot.x + plot.w} y1={y} y2={y} className="chart-grid" />
        <text x={plot.x - 8} y={y} textAnchor="end" dominantBaseline="central" className="chart-label">
          {Math.round(value)}
        </text>
      </g>,
    );
  }
  const xs = [...new Set([0, 0.5, 1].map((f) => Math.round((values.length - 1) * f)))];
  const line = values.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  const area = `M${px(0)},${plot.y + plot.h}L${line.replace(/ /g, "L")}L${px(values.length - 1)},${plot.y + plot.h}Z`;
  const bandPath = band
    ? "M" +
      highs.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join("L") +
      "L" +
      lows
        .map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`)
        .reverse()
        .join("L") +
      "Z"
    : null;
  const last = values.length - 1;
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height}>
          <defs>
            <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" style={{ stopColor: "var(--accent)" }} stopOpacity={0.3} />
              <stop offset="1" style={{ stopColor: "var(--accent)" }} stopOpacity={0} />
            </linearGradient>
          </defs>
          {grid}
          {xs.map((i) => (
            <text key={i} x={px(i)} y={plot.y + plot.h + 8} textAnchor="middle" dominantBaseline="hanging" className="chart-label">
              {i}
            </text>
          ))}
          {bandPath && <path d={bandPath} style={{ fill: "rgba(var(--accent-rgb), 0.12)" }} />}
          <path d={area} fill={`url(#${id}-fill)`} />
          <polyline points={line} className="chart-line" />
          {values.length <= 60 && values.map((v, i) => <circle key={i} cx={px(i)} cy={py(v)} r={3} className="chart-dot" />)}
          <circle cx={px(last)} cy={py(values[last] ?? 0)} r={7} className="chart-last-ring" />
          <circle cx={px(last)} cy={py(values[last] ?? 0)} r={4.5} className="chart-last" />
        </svg>
      )}
    </div>
  );
}

export function BarChart({ items }: { items: { name: string; rate: number; attempts: number }[] }): ReactElement {
  if (!items.length) return <div className="chart empty">{t("charts.no_themes")}</div>;
  return (
    <div className="bars">
      {items.map((item) => {
        const tone = item.rate >= 0.65 ? "good" : item.rate >= 0.45 ? "mid" : "bad";
        return (
          <div key={item.name} className="bar-row">
            <span className="bar-label" title={item.name}>
              {item.name}
            </span>
            <span className="bar-track">
              <span className={`bar-fill ${tone}`} style={{ width: `max(14px, ${(item.rate * 100).toFixed(1)}%)` }} />
            </span>
            <span className="bar-value">
              {Math.round(item.rate * 100)}% ({item.attempts})
            </span>
          </div>
        );
      })}
    </div>
  );
}
