// Portret trenera („Trener Maks”) w SVG — port ui/coach_avatar.py (te same kształty w jednostkach 0–100).
// Miny: neutral, happy, excited, thinking, concerned, shocked; trener mruga co kilka sekund.

import { useEffect, useId, useState, type ReactElement } from "react";

const SKIN = "rgb(243,198,162)";
const SKIN_SHADE = "rgb(222,166,128)";
const HAIR = "rgb(56,38,30)";
const HAIR_LIGHT = "rgb(92,64,48)";
const HOODIE = "rgb(34,44,80)";
const HOODIE_LIGHT = "rgb(54,68,116)";
const SHIRT = "rgb(232,237,247)";
const GLASSES = "rgb(26,28,38)";
const EYE = "rgb(32,28,34)";
const MOUTH = "rgb(122,40,50)";
const TONGUE = "rgb(218,104,110)";

type P = [number, number];

const line = (points: P[], color: string, width: number, key?: string): ReactElement => (
  <polyline key={key} points={points.map((p) => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />
);
const curve = (a: P, mid: P, b: P, color: string, width: number, key?: string): ReactElement => (
  <path key={key} d={`M${a[0]} ${a[1]}Q${mid[0]} ${mid[1]} ${b[0]} ${b[1]}`} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" />
);

function Eyebrows({ expression }: { expression: string }): ReactElement {
  const w = 1.9;
  switch (expression) {
    case "concerned":
      return <>{[line([[37, 36.5], [46, 33.5]], HAIR, w, "l"), line([[54, 33.5], [63, 36.5]], HAIR, w, "r")]}</>;
    case "excited":
    case "shocked":
      return <>{[curve([37, 33], [41.5, 30], [46, 32], HAIR, w, "l"), curve([54, 32], [58.5, 30], [63, 33], HAIR, w, "r")]}</>;
    case "thinking":
      return <>{[line([[37, 35.5], [46, 35.5]], HAIR, w, "l"), curve([54, 33], [58.5, 30.5], [63, 33.5], HAIR, w, "r")]}</>;
    case "happy":
      return <>{[curve([37, 35.5], [41.5, 33], [46, 34.5], HAIR, w, "l"), curve([54, 34.5], [58.5, 33], [63, 35.5], HAIR, w, "r")]}</>;
    default:
      return <>{[curve([37, 36], [41.5, 34.5], [46, 35.2], HAIR, w, "l"), curve([54, 35.2], [58.5, 34.5], [63, 36], HAIR, w, "r")]}</>;
  }
}

function Eyes({ expression, blink }: { expression: string; blink: boolean }): ReactElement {
  return (
    <>
      {[42, 58].map((cx) => {
        if (blink || expression === "excited") {
          return expression === "excited"
            ? curve([cx - 2.6, 46.2], [cx, 42.6], [cx + 2.6, 46.2], EYE, 1.5, String(cx))
            : curve([cx - 2.6, 45.4], [cx, 46.4], [cx + 2.6, 45.4], EYE, 1.3, String(cx));
        }
        const [dx, dy] = expression === "thinking" ? [0.9, -1.1] : [0, 0];
        const [w, h] = expression === "shocked" ? [5.2, 6.6] : [4.3, 5.4];
        return (
          <g key={cx}>
            {expression === "shocked" && <ellipse cx={cx} cy={45} rx={3.6} ry={4.2} fill="#fff" />}
            <ellipse cx={cx + dx} cy={45 + dy} rx={w / 2} ry={h / 2} fill={EYE} />
            <circle cx={cx + 0.9 + dx} cy={43.7 + dy} r={0.9} fill="#fff" />
          </g>
        );
      })}
    </>
  );
}

function Mouth({ expression }: { expression: string }): ReactElement {
  if (expression === "happy" || expression === "excited") {
    const depth = expression === "excited" ? 7.5 : 5.0;
    const half = expression === "excited" ? 7.0 : 6.0;
    const top = 58;
    return (
      <g>
        <path d={`M${50 - half} ${top}L${50 + half} ${top}Q50 ${top + 2 * depth} ${50 - half} ${top}Z`} fill={MOUTH} />
        <polygon
          points={`${50 - half + 0.8},${top + 0.3} ${50 + half - 0.8},${top + 0.3} ${50 + half - 2.2},${top + 2} ${50 - half + 2.2},${top + 2}`}
          fill="rgb(250,250,252)"
        />
        <ellipse cx={50} cy={top + depth * 0.8} rx={half * 0.45} ry={depth * 0.25} fill={TONGUE} />
      </g>
    );
  }
  if (expression === "shocked") return <ellipse cx={50} cy={61.6} rx={2.4} ry={3.1} fill={MOUTH} />;
  if (expression === "thinking") return curve([47, 61.5], [51, 61.2], [54.5, 59.8], MOUTH, 1.4);
  if (expression === "concerned") return curve([45.5, 62], [50, 59.6], [54.5, 62], MOUTH, 1.4);
  return curve([44.5, 59.3], [50, 63.2], [55.5, 59.3], MOUTH, 1.5);
}

export function CoachAvatar({ expression = "neutral", size = 64 }: { expression?: string; size?: number }): ReactElement {
  const id = useId().replace(/:/g, "");
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    let timer = 0;
    const schedule = (): void => {
      timer = window.setTimeout(
        () => {
          setBlink(true);
          timer = window.setTimeout(() => {
            setBlink(false);
            schedule();
          }, 130);
        },
        2600 + Math.random() * 2600,
      );
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, []);

  const cells: ReactElement[] = [];
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      if ((row + col) % 2 === 0) cells.push(<rect key={`${row}-${col}`} x={col * 12.5} y={row * 12.5} width={12.5} height={12.5} />);
    }
  }
  const cheeks = expression === "happy" || expression === "excited";
  return (
    <svg className={`coach-avatar expr-${expression}`} width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="Coach">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="rgb(40,196,180)" />
          <stop offset="1" stopColor="rgb(124,92,236)" />
        </linearGradient>
        <clipPath id={`${id}-clip`}>
          <circle cx="50" cy="50" r="50" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        <rect width="100" height="100" fill={`url(#${id}-bg)`} />
        <g fill="rgba(255,255,255,0.055)">{cells}</g>
        <circle cx="30" cy="22" r="34" fill="rgba(255,255,255,0.13)" />
        {/* tułów */}
        <ellipse cx="50" cy="106" rx="44" ry="32" fill={HOODIE} />
        <ellipse cx="50" cy="81" rx="28" ry="11" fill={HOODIE_LIGHT} />
        <ellipse cx="50" cy="78" rx="13" ry="6" fill={SHIRT} />
        <polygon points="42,58 58,58 58,74 50,79 42,74" fill={SKIN_SHADE} />
        {line(
          [
            [44, 84],
            [43, 97],
          ],
          "rgb(210,220,240)",
          1.2,
        )}
        {line(
          [
            [56, 84],
            [57, 97],
          ],
          "rgb(210,220,240)",
          1.2,
        )}
        <image href="/pieces/wN.svg" x="58" y="80" width="14" height="14" />
        {/* głowa */}
        <ellipse cx="50" cy="30" rx="23" ry="17" fill={HAIR} />
        <ellipse cx="29.5" cy="45" rx="4" ry="6" fill={SKIN_SHADE} />
        <ellipse cx="70.5" cy="45" rx="4" ry="6" fill={SKIN_SHADE} />
        <ellipse cx="29.5" cy="45" rx="2" ry="3" fill="rgb(206,148,112)" />
        <ellipse cx="70.5" cy="45" rx="2" ry="3" fill="rgb(206,148,112)" />
        <ellipse cx="50" cy="42.5" rx="20" ry="23.5" fill={SKIN} />
        <path d="M29 38L29 27L34 18L43 13.5L53 13L63 16L69.5 23L71 36L68 29L63 24.5Q52 22 40 30L35 31L31 35Z" fill={HAIR} />
        {curve([38, 18.5], [50, 14.5], [61, 18], HAIR_LIGHT, 1.3)}
        <polygon points="50,48.5 47.6,54.5 50.8,55.4" fill={SKIN_SHADE} />
        {cheeks && (
          <g fill="rgba(240,120,120,0.27)">
            <ellipse cx="36" cy="53.75" rx="3.5" ry="2.25" />
            <ellipse cx="64" cy="53.75" rx="3.5" ry="2.25" />
          </g>
        )}
        <Eyebrows expression={expression} />
        <Eyes expression={expression} blink={blink} />
        {/* okulary */}
        <circle cx="42" cy="45" r="7.3" fill="rgba(200,230,255,0.16)" />
        <circle cx="58" cy="45" r="7.3" fill="rgba(200,230,255,0.16)" />
        <circle cx="42" cy="45" r="7.6" fill="none" stroke={GLASSES} strokeWidth="1.35" />
        <circle cx="58" cy="45" r="7.6" fill="none" stroke={GLASSES} strokeWidth="1.35" />
        {curve([49.3, 44.6], [50, 43.6], [50.7, 44.6], GLASSES, 1.3)}
        {line(
          [
            [34.5, 44],
            [30.5, 42.5],
          ],
          GLASSES,
          1.3,
        )}
        {line(
          [
            [65.5, 44],
            [69.5, 42.5],
          ],
          GLASSES,
          1.3,
        )}
        {curve([38, 41.5], [39.2, 40.2], [41, 39.6], "#fff", 0.8)}
        {curve([54, 41.5], [55.2, 40.2], [57, 39.6], "#fff", 0.8)}
        <Mouth expression={expression} />
      </g>
    </svg>
  );
}
