// State snapshots sent by the Python server (tacticmind/web). Field names as in the JSON.

export type Color = "white" | "black";
export type ScreenName = "home" | "play" | "coach" | "coach_game" | "stats" | "howto";
export type Tone = "text" | "muted" | "accent" | "red" | "amber" | "violet" | "brilliant" | "soft";

export interface Feedback {
  square: string;
  kind: string; // ok | bad | brilliant | cls:<class>
  seq: number;
  effect: boolean;
}

export interface BoardSnapshot {
  fen: string;
  seq: number;
  anim: "move" | "undo" | "none";
  orientation: Color;
  player: Color;
  interactive: boolean;
  legal: string[];
  /** Where the other side's pieces could go (they can be picked up to look, not moved). */
  peek: string[];
  lastMove: string | null;
  check: string | null;
  hint: string | null;
  arrows: [string, string, string][];
  feedback: Feedback | null;
}

export interface Score {
  cp: number | null;
  mate: number | null;
  value: number;
  label: string;
}

export interface TopBarSnapshot {
  source: "puzzles" | "coach";
  rating: number;
  rd: number | null;
  caption: string;
  streak: number;
  delta: number | null;
  deltaSeq: number;
  sound: boolean;
  volume: number;
}

export interface UiSettings {
  showFps: boolean;
  fpsLimit: number; // 0 = unlimited (display refresh rate)
  theme: "dark" | "light";
  board: "green" | "terracotta" | "slate";
  /** The evaluation bar in a game against the coach. */
  coachEval: boolean;
}

export interface Thought {
  text: string;
  kind: string;
}

export interface TreeRow {
  move: string;
  san: string;
  value: string;
  exact: boolean;
  pruned: boolean;
  tt: boolean;
}

export interface TreeRoot extends TreeRow {
  children: TreeRow[];
  more: number;
}

export interface BrainSnapshot {
  mode: "hidden" | "hint" | "full";
  running: boolean;
  hasInfo: boolean;
  statusNote: string;
  counters: { label: string; value: string }[];
  candidates: { score: string; white: boolean; line: string }[] | null;
  thoughts: Thought[];
  explanation: string[];
  tree: TreeRoot[] | null;
}

export interface ButtonState {
  visible: boolean;
  enabled: boolean;
}

export interface Confirm {
  text: string;
  yes: string;
}

export interface PlaySnapshot {
  puzzle: number;
  board: BoardSnapshot;
  eval: { hidden: boolean; score: Score | null; whiteBottom: boolean };
  card: {
    side: Color;
    title: string;
    rating: string;
    finished: boolean;
    message: string;
    color: Tone;
    messageSeq: number;
    detail: string;
    themes: string;
    delta: number | null;
    why: string[];
  };
  buttons: Record<"hint" | "solution" | "retry" | "next" | "prev" | "fwd", ButtonState>;
  preview: { index: number; total: number; label: string; line: string } | null;
  confirm: Confirm | null;
  brain: BrainSnapshot;
  explainSeq: number;
  training: Training;
  notice: string | null;
}

export interface ThemeOption {
  id: string;
  name: string;
  count: string;
  stats: string;
  weak: boolean;
}

export interface RushState {
  minutes: number;
  /** Seconds left; null in Survival (no clock). */
  left: number | null;
  solved: number;
  strikes: number;
  maxStrikes: number;
  best: number;
  over: "time" | "strikes" | "stopped" | null;
  overTitle: string;
  result: string;
  record: boolean;
  results: { rating: number; solved: boolean }[];
}

export interface Training {
  kind: "rated" | "theme" | "review" | "rush";
  theme: string | null;
  label: string;
  rush: RushState | null;
  review: number;
  reviewLabel: string;
  rushBest: Record<string, number>;
  themes: ThemeOption[];
}

export interface Strip {
  player: boolean;
  name: string;
  detail: string;
  toMove: boolean;
  capturedColor: Color;
  captured: string[];
  diff: number;
}

export interface Control {
  id: string;
  label: string;
  short: string;
  enabled: boolean;
  style: string;
}

export interface CoachGameSnapshot {
  game: number;
  board: BoardSnapshot;
  expression: string;
  strips: Strip[];
  card: {
    subtitle: string;
    opening: string;
    comment: { text: string; cls: string | null; seq: number };
    side: { text: string; busy: boolean; threat: boolean } | null;
    buttons: { id: string; label: string; style: string }[];
  };
  controls: Control[];
  nav: { prev: boolean; next: boolean };
  moves: { first: number; offset: number; current: number; list: { san: string; cls: string | null; player: boolean }[] };
  /** The engine's evaluation of the position on the board (null while not known yet). */
  eval: { score: Score | null; whiteBottom: boolean };
  summary: {
    result: "win" | "loss" | "draw";
    title: string;
    reason: string;
    accuracy: { label: string; value: string }[];
    rows: { cls: string; you: number; trainer: number }[];
    lines: { text: string; color: Tone }[];
  } | null;
  /** After the game: White's winning chance (0–100) after every ply (index 0 = initial position) and the PGN. */
  review: { evals: number[]; current: number; pgn: string; archived: boolean } | null;
  notice: string | null;
  confirm: Confirm | null;
}

export interface SavedGameRow {
  index: number;
  result: "win" | "loss" | "draw";
  color: Color;
  elo: number;
  opening: string;
  accuracy: number | null;
  moves: number;
  date: string;
  delta: number;
  reviewable: boolean;
}

export interface OpeningRow {
  id: string;
  eco: string;
  side: Color;
  line: string;
  stars: number;
}

export interface CoachMenuSnapshot {
  greeting: string;
  elo: number;
  sliderElo: number;
  adaptive: boolean;
  level: string;
  levelLabel: string;
  levelEnabled: boolean;
  levelActive: boolean;
  note: string;
  color: "white" | "random" | "black";
  range: [number, number, number];
  inProgress: boolean;
  openings: OpeningRow[];
  games: SavedGameRow[];
  confirm: Confirm | null;
}

export interface StatsSnapshot {
  system: "glicko" | "elo";
  cards: { label: string; value: string; accent: string }[];
  ratings: number[];
  band: number[] | null;
  themes: { name: string; rate: number; attempts: number }[];
  confirm: boolean;
}

export interface DemoNode {
  id: string;
  value: number | null;
  children: DemoNode[];
}

export interface DemoStep {
  node: string;
  text: string;
  value: number | null;
  cut: string[];
}

export interface HowToSnapshot {
  positions: string[];
  position: number;
  depth: number;
  running: boolean;
  status: string;
  error: boolean;
  result: {
    label: string;
    rows: { name: string; share?: number; stats?: string; skipped?: string }[];
    summary: string;
    same: boolean;
  } | null;
  tree: DemoNode;
  demos: Record<"minimax" | "alphabeta", { steps: DemoStep[]; result: string }>;
  sections: string[];
}

export interface HomeSnapshot {
  info: string;
  source: string;
  demo: { fen: string; last: string; move: string; label: string };
}

export type ViewSnapshot = PlaySnapshot | CoachGameSnapshot | CoachMenuSnapshot | StatsSnapshot | HowToSnapshot | HomeSnapshot;

export interface AppState {
  screen: ScreenName;
  lang: string;
  topbar: TopBarSnapshot;
  settings: UiSettings;
  view: ViewSnapshot;
}

export type FxEvent =
  | { type: "sound"; name: string }
  | { type: "shake"; board: string }
  | { type: "celebrate"; board: string; square: string };
