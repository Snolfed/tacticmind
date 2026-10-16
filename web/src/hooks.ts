import { useEffect, useRef } from "react";

/** Skróty klawiszowe ekranu (pomijane, gdy pisze się w polu tekstowym albo otwarte jest okno). */
export function useKeys(handler: (event: KeyboardEvent) => void, active = true): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent): void => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        if (!(target instanceof HTMLInputElement && target.type === "range" && event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
      }
      if (document.querySelector(".modal-backdrop")) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      ref.current(event);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);
}
