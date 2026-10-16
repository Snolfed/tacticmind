// Wspólne kontrolki: przycisk, przełącznik segmentowy, okno potwierdzenia.

import { useEffect, useRef, type ReactElement, type ReactNode } from "react";
import { t, useLanguage } from "../i18n";

export type ButtonStyle = "primary" | "secondary" | "ghost" | "danger" | "violet";

export function Button({
  children,
  onClick,
  style = "secondary",
  disabled = false,
  className,
  title,
  pill = false,
  active = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  style?: ButtonStyle | string;
  disabled?: boolean;
  className?: string;
  title?: string;
  pill?: boolean;
  active?: boolean;
}): ReactElement {
  return (
    <button
      type="button"
      className={`btn btn-${style}${pill ? " pill" : ""}${active ? " active" : ""}${className ? " " + className : ""}`}
      disabled={disabled}
      title={title}
      aria-label={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  accent = "violet",
  className,
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  accent?: "violet" | "accent";
  className?: string;
}): ReactElement {
  const index = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  return (
    <div
      className={`segmented accent-${accent}${className ? " " + className : ""}`}
      role="tablist"
      style={{ "--count": options.length, "--index": index } as React.CSSProperties}
    >
      <span className="segmented-thumb" aria-hidden="true" />
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          className={option.value === value ? "selected" : ""}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Okno potwierdzenia na środku ekranu (Enter = tak, Esc = nie). */
export function ConfirmDialog({
  title,
  text,
  yes,
  onYes,
  onNo,
}: {
  title?: string;
  text: string;
  yes: string;
  onYes: () => void;
  onNo: () => void;
}): ReactElement {
  useLanguage();
  const yesRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    yesRef.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onNo();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onNo]);
  return (
    <div className="modal-backdrop" onPointerDown={(e) => e.target === e.currentTarget && onNo()}>
      <div className="modal card" role="dialog" aria-modal="true">
        {title && <h2>{title}</h2>}
        <p>{text}</p>
        <div className="modal-buttons">
          <button type="button" className="btn btn-secondary" onClick={onNo}>
            {t("common.cancel")}
          </button>
          <button ref={yesRef} type="button" className="btn btn-danger" onClick={onYes}>
            {yes}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }): ReactElement {
  return <section className={`card${className ? " " + className : ""}`}>{children}</section>;
}
