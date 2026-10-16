// Connection to the game logic. The interface talks to it through a single narrow channel:
// actions (JSON) flow one way, state snapshots and "fx" events flow the other.
// Today the other side is a local Python server (SSE + POST); for a mobile version
// it is enough to swap the transport, and the rest of the interface stays unchanged.

import { useSyncExternalStore } from "react";
import type { AppState, FxEvent } from "./types";

export type Action = { type: string } & Record<string, unknown>;

export interface Transport {
  connect(onState: (state: AppState) => void, onFx: (events: FxEvent[]) => void, onStatus: (online: boolean) => void): void;
  send(action: Action): void;
}

class SseTransport implements Transport {
  connect(onState: (state: AppState) => void, onFx: (events: FxEvent[]) => void, onStatus: (online: boolean) => void): void {
    const source = new EventSource("/api/events");
    source.addEventListener("state", (event) => onState(JSON.parse((event as MessageEvent<string>).data) as AppState));
    source.addEventListener("fx", (event) => onFx(JSON.parse((event as MessageEvent<string>).data) as FxEvent[]));
    source.onopen = () => onStatus(true);
    source.onerror = () => onStatus(false); // EventSource reconnects by itself
  }

  send(action: Action): void {
    void fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TacticMind": "1" },
      body: JSON.stringify(action),
    }).catch(() => undefined);
  }
}

type Listener = () => void;

class Store {
  state: AppState | null = null;
  online = false;
  private listeners = new Set<Listener>();
  private fxListeners = new Set<(event: FxEvent) => void>();
  private transport: Transport;

  constructor(transport: Transport) {
    this.transport = transport;
  }

  start(): void {
    this.transport.connect(
      (state) => {
        this.state = state;
        this.online = true;
        this.emit();
      },
      (events) => events.forEach((event) => this.fxListeners.forEach((listener) => listener(event))),
      (online) => {
        this.online = online;
        this.emit();
      },
    );
  }

  send(action: Action): void {
    this.transport.send(action);
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  onFx(listener: (event: FxEvent) => void): () => void {
    this.fxListeners.add(listener);
    return () => this.fxListeners.delete(listener);
  }

  private emit(): void {
    this.listeners.forEach((listener) => listener());
  }
}

export const store = new Store(new SseTransport());

export function useAppState(): AppState | null {
  return useSyncExternalStore(store.subscribe, () => store.state);
}

export function useOnline(): boolean {
  return useSyncExternalStore(store.subscribe, () => store.online);
}

export function send(action: Action): void {
  store.send(action);
}

/** A screen action, e.g. screenAction("play", "hint"). */
export function screenAction(screen: string, name: string, data: Record<string, unknown> = {}): void {
  store.send({ type: "screen", screen, name, data });
}

export function go(screen: string): void {
  store.send({ type: "go", screen });
}
