/**
 * Shared types. Most mirror backend payloads: Source <- context.Source.public(), Step <- RunContext.step(),
 * WeatherWidget <- tools/weather.get_weather(), Thread/ChatMessage <- store/db.py to_dict().
 */

/** Research mode toggle: let the router decide, or force the quick ReAct / deep-research path. */
export type Mode = "auto" | "quick" | "deep";

/** Background scene families (components/scenes). */
export type SceneName =
  | "weather" | "travel" | "news" | "finance" | "sports" | "tech" | "space" | "health" | "food" | "default";

/** Fine-tuning for a scene: real weather at the place, or the landscape of a travel destination. */
export interface SceneParams {
  condition?: "clear" | "partly-cloudy" | "cloudy" | "rain" | "snow" | "storm" | "fog";
  is_day?: boolean;
  setting?: "beach" | "mountain" | "city" | "desert" | "snow" | "countryside";
  location?: string;
}

export interface SceneState {
  scene: SceneName;
  params: SceneParams;
}

/** A web page or API result the agent saw. `n` is its citation number, set only for cited sources. */
export interface Source {
  id: number;            // registry id (the model's S<id>)
  n?: number;            // display number of [n] chips
  url: string;
  title: string;
  domain: string;
  snippet: string;
  published?: string | null;
  kind: string;
  fetched: boolean;      // the full page was read (not just a search snippet)
  favicon: string;
}

/** One line of the research timeline. Created "running", then updated by id. */
export interface Step {
  id: number;
  kind?: "think" | "search" | "news" | "fetch" | "weather" | "write";
  label?: string;
  status: "running" | "done" | "failed";
  provider?: string;     // search provider that answered (search steps)
  tier?: string;         // fetch tier that worked, e.g. "http", "jina", "site_api:wikipedia" (fetch steps)
  count?: number;
  domains?: string[];
  url?: string;
  title?: string;
  detail?: string;
}

/** A deep-research plan item (deepagents' write_todos). */
export interface Todo {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

/** Live weather card data (Open-Meteo), temperatures in °C. */
export interface WeatherWidget {
  type: "weather";
  source_id: number;
  location: { name: string; admin1?: string; country?: string; timezone?: string };
  current: {
    time: string; temperature_c: number; feels_like_c: number; humidity: number; wind_kmh: number;
    precipitation_mm: number; condition: string; is_day: boolean;
  };
  hourly: { time: string; temperature_c: number; precip_prob: number | null; condition: string }[];
  daily: { date: string; condition: string; scene: string; max_c: number; min_c: number; precip_prob: number; sunrise: string; sunset: string }[];
  scene?: { condition: string; is_day: boolean };
}

/** Strip of recent articles from a news search. */
export interface NewsWidget {
  type: "news";
  items: { title: string; url: string; domain: string; published?: string | null; snippet: string }[];
}

export type Widget = WeatherWidget | NewsWidget;

/** The router's decision for a turn (intent, quick/deep, scene). */
export interface Route {
  intent?: string;
  mode?: "quick" | "deep";
  scene?: SceneName;
  params?: SceneParams;
  location?: string | null;
  search_query?: string;
}

/** Everything attached to an assistant message besides its text (also persisted, so reloads look the same). */
export interface AssistantMeta {
  run_id?: string;
  sources?: Source[];          // cited, numbered
  all_sources?: Source[];      // everything the agent saw
  widgets?: Widget[];
  route?: Route;
  steps?: Step[];
  plan?: Todo[];
  follow_ups?: string[];
  usage?: { searches: number; fetches: number; sources: number; seconds: number };
  invalid_citations?: string[];
  notices?: string[];
  error?: string;
}

/** A message in the conversation. `streaming` is client-only: true while tokens are still arriving. */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: AssistantMeta;
  created_at: string;
  streaming?: boolean;
}

/** A sidebar thread. */
export interface Thread {
  id: string;
  title: string;
  pinned: boolean;
  scene: SceneName;
  created_at: string;
  updated_at: string;
}

/** A pre-loaded question card on the empty state (backend/app/api/suggestions.py). */
export interface Suggestion {
  category: string;
  scene: SceneName;
  icon: string;
  question: string;
  params?: SceneParams;
}
