// Tłumaczenia: te same słowniki co w Pythonie (tacticmind/i18n), pobierane z /api/strings.
// Stałe napisy interfejsu formatujemy tutaj; teksty zależne od stanu gry przychodzą gotowe.

import { useSyncExternalStore } from "react";
import { UI_STRINGS } from "./uiStrings";

interface Payload {
  default: string;
  languages: Record<string, { name: string; strings: Record<string, string> }>;
}

let payload: Payload = { default: "pl", languages: {} };
let language = "pl";
const listeners = new Set<() => void>();

export async function loadStrings(): Promise<void> {
  const response = await fetch("/api/strings");
  payload = (await response.json()) as Payload;
  listeners.forEach((listener) => listener());
}

export function setLanguage(code: string): void {
  if (code === language) return;
  language = code;
  document.documentElement.lang = code;
  listeners.forEach((listener) => listener());
}

export function languages(): { code: string; name: string }[] {
  return Object.entries(payload.languages).map(([code, value]) => ({ code, name: value.name }));
}

function lookup(key: string): string | undefined {
  return (
    payload.languages[language]?.strings[key] ??
    UI_STRINGS[language]?.[key] ??
    payload.languages[payload.default]?.strings[key] ??
    UI_STRINGS[payload.default]?.[key]
  );
}

export function has(key: string): boolean {
  return lookup(key) !== undefined;
}

/** Tekst w bieżącym języku; pola `{nazwa}` jak w str.format w Pythonie. */
export function t(key: string, params: Record<string, string | number> = {}): string {
  const text = lookup(key) ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function pluralForm(n: number, code: string = language): "one" | "few" | "many" {
  const value = Math.abs(n);
  if (code === "pl") {
    if (value === 1) return "one";
    if ([2, 3, 4].includes(value % 10) && ![12, 13, 14].includes(value % 100)) return "few";
    return "many";
  }
  return value === 1 ? "one" : "many";
}

/** Tekst z liczbą: klucze `key.one` / `key.few` / `key.many`. */
export function tn(key: string, n: number, params: Record<string, string | number> = {}): string {
  for (const candidate of [`${key}.${pluralForm(n)}`, `${key}.many`, key]) {
    if (has(candidate)) return t(candidate, { n, ...params });
  }
  return key;
}

/** Komponenty, które używają t(), odświeżają się po zmianie języka. */
export function useLanguage(): string {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => language + ":" + Object.keys(payload.languages).length,
  );
}

// Do testów.
export function _setPayload(value: Payload, code: string): void {
  payload = value;
  language = code;
}
