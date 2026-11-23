export type Mode = "auto" | "quick" | "deep";

export type SceneName =
  | "weather" | "travel" | "news" | "finance" | "sports" | "tech" | "space" | "health" | "food" | "default";

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

export interface Source {
  id: number;
  n?: number;
  url: string;
  title: string;
  domain: string;
  snippet: string;
  published?: string | null;
  kind: string;
  fetched: boolean;
  favicon: string;
}

export interface Step {
  id: number;
  kind?: "think" | "search" | "news" | "fetch" | "weather" | "write";
  label?: string;
  status: "running" | "done" | "failed";
  provider?: string;
  tier?: string;
  count?: number;
  domains?: string[];
  url?: string;
  title?: string;
  detail?: string;
}

export interface Todo {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

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
}

export interface NewsWidget {
  type: "news";
  items: { title: string; url: string; domain: string; published?: string | null; snippet: string }[];
}

export type Widget = WeatherWidget | NewsWidget;

export interface Route {
  intent?: string;
  mode?: "quick" | "deep";
  scene?: SceneName;
  params?: SceneParams;
  location?: string | null;
  search_query?: string;
}

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

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: AssistantMeta;
  created_at: string;
  streaming?: boolean;
}

export interface Thread {
  id: string;
  title: string;
  pinned: boolean;
  scene: SceneName;
  created_at: string;
  updated_at: string;
}

export interface Suggestion {
  category: string;
  scene: SceneName;
  icon: string;
  question: string;
  params?: SceneParams;
}
