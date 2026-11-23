import type { Page } from "@playwright/test";

const API = "http://localhost:8000";

const weatherWidget = {
  type: "weather", source_id: 1,
  location: { name: "Mumbai", admin1: "Maharashtra", country: "India", timezone: "Asia/Kolkata" },
  current: { time: "2026-11-23T14:00", temperature_c: 31.2, feels_like_c: 33.0, humidity: 55, wind_kmh: 12, precipitation_mm: 0, condition: "Light rain", is_day: true },
  hourly: Array.from({ length: 12 }, (_, i) => ({ time: `2026-11-23T${String(14 + (i % 10)).padStart(2, "0")}:00`, temperature_c: 30 - i * 0.3, precip_prob: 40, condition: "rain" })),
  daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-11-${23 + i}`, condition: "Light rain", scene: "rain", max_c: 32, min_c: 23, precip_prob: 60, sunrise: "", sunset: "" })),
};

const source = { id: 1, n: 1, url: "https://open-meteo.com/en/docs#latitude=19.07&longitude=72.88", title: "Open-Meteo forecast for Mumbai", domain: "open-meteo.com", snippet: "", published: null, kind: "api", fetched: true, favicon: "" };

export function sse(events: [string, unknown][]) {
  return events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

export async function mockBackend(page: Page) {
  await page.route(`${API}/api/threads`, (r) => r.fulfill({ json: [] }));
  await page.route(`${API}/api/suggestions`, (r) => r.fulfill({ status: 404, body: "" }));
  await page.route(`${API}/api/chat`, (r) =>
    r.fulfill({
      headers: { "content-type": "text/event-stream" },
      body: sse([
        ["thread", { thread_id: "t-1" }],
        ["start", { run_id: "r-1" }],
        ["route", { intent: "weather", mode: "quick", query: "Mumbai weather today" }],
        ["scene", { scene: "weather", params: { location: "Mumbai" }, final: false }],
        ["step", { id: 1, kind: "weather", label: "Mumbai", status: "running" }],
        ["source", source],
        ["widget", weatherWidget],
        ["scene", { scene: "weather", params: { condition: "rain", is_day: true }, final: true }],
        ["step", { id: 1, status: "done", title: "Mumbai, Maharashtra, India" }],
        ["token", { text: "It's **31°C** with light rain in Mumbai [1]. " }],
        ["token", { text: "Carry an umbrella [1]." }],
        ["citations", { sources: [source], invalid_removed: [] }],
        ["followups", { items: ["Will it rain tomorrow?", "What about Pune?"] }],
        ["done", { answer: "It's **31°C** with light rain in Mumbai [1]. Carry an umbrella [1].", sources: [source], all_sources: [source], widgets: [weatherWidget], route: { intent: "weather", mode: "quick", scene: "weather", params: { condition: "rain" } }, usage: { searches: 0, fetches: 0, sources: 1, seconds: 3.1 } }],
      ]),
    }),
  );
}
