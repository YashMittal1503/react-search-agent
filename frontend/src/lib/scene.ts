import type { SceneName, SceneState } from "./types";

/** Instant client-side guess so the background reacts the moment you hit send;
 *  the backend router (and real weather data) refine it a moment later. */
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

const SETTINGS: [NonNullable<SceneState["params"]["setting"]>, RegExp][] = [
  ["beach", /\b(beach|island|goa|bali|maldives|coast|seaside)\b/i],
  ["mountain", /\b(mountain|hike|trek|alps|himalaya|manali|ski)\b/i],
  ["desert", /\b(desert|dubai|sahara|rajasthan|jaisalmer)\b/i],
  ["snow", /\b(snow|iceland|lapland|winter)\b/i],
];

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

export const SCENE_LABEL: Record<SceneName, string> = {
  weather: "Sky", travel: "Journey", news: "Newsroom", finance: "Markets", sports: "Stadium",
  tech: "Circuit", space: "Cosmos", health: "Calm", food: "Kitchen", default: "Aurora",
};
