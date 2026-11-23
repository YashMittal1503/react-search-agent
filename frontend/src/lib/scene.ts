/**
 * Client-side scene guessing. These rules mirror the backend's heuristic router (app/agent/router.py), so the
 * first guess usually agrees with the server's later `scene` event.
 */
import type { SceneName, SceneState } from "./types";

/** Instant client-side guess so the background reacts the moment you hit send;
 *  the backend router (and real weather data) refine it a moment later. First matching rule wins. */
const RULES: [SceneName, RegExp][] = [
  ["weather", /\b(weather|forecast|temperature|rain|raining|rainy|snow|snowing|humidity|umbrella|sunny|windy|degrees)\b/i],
  ["travel", /\b(itinerary|trip|travel|vacation|holiday|visit|things to do|places to see|hotel|flight|tour|backpack|beach(es)?)\b/i],
  ["news", /\b(news|latest|headlines|breaking|today's|this week|trending|trends|announced)\b/i],
  ["finance", /\b(stock|share price|market|nasdaq|sensex|nifty|crypto|bitcoin|inflation|interest rate|earnings|ipo|gdp)\b/i],
  ["sports", /\b(match|score|football|soccer|cricket|nba|nfl|ipl|world cup|tennis|f1|formula 1|olympics|league|grand prix)\b/i],
  ["space", /\b(space|nasa|planet|galaxy|physics|quantum|telescope|mars|moon|webb|astronom\w*|black hole)\b/i],
  ["tech", /\b(ai|llm|llms|gpu|iphone|android|software|programming|python|javascript|startup|chip|openai|nvidia|app)\b/i],
  ["health", /\b(health|symptom|disease|diet|exercise|vaccine|medicine|sleep|calories|protein|fasting)\b/i],
  ["food", /\b(recipe|restaurant|cook|food|dish|cuisine|cafe|pizza|dinner|breakfast|lunch|dough)\b/i],
];

/** Travel sub-settings: which landscape the travel scene paints (default: city skyline). */
const SETTINGS: [NonNullable<SceneState["params"]["setting"]>, RegExp][] = [
  ["beach", /\b(beach|island|goa|bali|maldives|coast|seaside)\b/i],
  ["mountain", /\b(mountain|hike|trek|alps|himalaya|manali|ski)\b/i],
  ["desert", /\b(desert|dubai|sahara|rajasthan|jaisalmer)\b/i],
  ["snow", /\b(snow|iceland|lapland|winter)\b/i],
];

/** Pick a scene (and travel setting) from the message text alone. */
export function guessScene(text: string): SceneState {
  for (const [scene, rx] of RULES) {
    if (rx.test(text)) {
      if (scene === "travel") {
        const setting = SETTINGS.find(([, r]) => r.test(text))?.[0] ?? "city";
        return { scene, params: { setting } };
      }
      return { scene, params: {} };
    }
  }
  return { scene: "default", params: {} };
}

/** Human-friendly scene names shown in the header's scene chip. */
export const SCENE_LABEL: Record<SceneName, string> = {
  weather: "Sky", travel: "Journey", news: "Newsroom", finance: "Markets", sports: "Stadium",
  tech: "Circuit", space: "Cosmos", health: "Calm", food: "Kitchen", default: "Aurora",
};
