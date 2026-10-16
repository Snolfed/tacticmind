// Ikony wektorowe (kolor z CSS: currentColor) — ostre przy każdej skali ekranu.

import type { ReactElement, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: IconProps & { children: React.ReactNode }): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconSoundOn = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" stroke="none" />
    <path d="M15.5 9a4.2 4.2 0 0 1 0 6" />
    <path d="M18 6.5a7.6 7.6 0 0 1 0 11" />
  </Svg>
);

export const IconSoundOff = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" stroke="none" />
    <path d="M16 9.5l5 5M21 9.5l-5 5" />
  </Svg>
);

export const IconFullscreen = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </Svg>
);

export const IconFullscreenExit = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
  </Svg>
);

export const IconSettings = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </Svg>
);

export const IconChevronLeft = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M14.5 6l-6 6 6 6" />
  </Svg>
);

export const IconChevronRight = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M9.5 6l6 6-6 6" />
  </Svg>
);

export const IconClose = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);

export const IconCheck = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);

export const IconFlame = (p: IconProps): ReactElement => (
  <svg width={p.size ?? 20} height={p.size ?? 20} viewBox="0 0 24 24" aria-hidden="true" className={p.className}>
    <defs>
      <linearGradient id="flame-grad" x1="0" y1="1" x2="0" y2="0">
        <stop offset="0" stopColor="#f43f5e" />
        <stop offset="0.55" stopColor="#fb923c" />
        <stop offset="1" stopColor="#fbbf24" />
      </linearGradient>
    </defs>
    <path
      d="M12 2.5c.6 3.2 4.8 5.6 4.8 10.6A4.8 4.8 0 0 1 12 18a4.8 4.8 0 0 1-4.8-4.9c0-2.2 1.1-3.6 2.1-4.6.2 1.6.9 2.6 1.9 3.1-.4-3 .1-6.4.8-9.1z"
      transform="translate(0 2.5)"
      fill="url(#flame-grad)"
    />
    <path d="M12 13.2c.9 1.1 2 1.9 2 3.6a2 2 0 0 1-4 0c0-1.3.9-2.3 2-3.6z" transform="translate(0 2.5)" fill="#fde68a" />
  </svg>
);

export const IconBolt = (p: IconProps): ReactElement => (
  <Svg {...p}>
    <path d="M13 3L5 13.5h6L10 21l8-10.5h-6z" fill="currentColor" stroke="none" />
  </Svg>
);
