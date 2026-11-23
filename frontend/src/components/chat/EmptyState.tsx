"use client";

import { motion } from "motion/react";
import {
  Cpu, CloudSun, HeartPulse, Newspaper, Palmtree, Plane, Rocket, Search, TrendingUp, Trophy, Umbrella, Utensils,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Suggestion } from "@/lib/types";
import { useChat } from "@/store/chat";

const ICONS: Record<string, typeof Search> = {
  "cloud-sun": CloudSun, umbrella: Umbrella, plane: Plane, palmtree: Palmtree, newspaper: Newspaper, cpu: Cpu,
  "trending-up": TrendingUp, rocket: Rocket, trophy: Trophy, utensils: Utensils, "heart-pulse": HeartPulse, search: Search,
};

const FALLBACK: Suggestion[] = [
  { category: "Weather", scene: "weather", icon: "cloud-sun", question: "What's the weather in Mumbai today?" },
  { category: "Travel", scene: "travel", icon: "plane", params: { setting: "city" }, question: "Plan a 4-day Kyoto itinerary for early spring on a mid-range budget" },
  { category: "News", scene: "news", icon: "newspaper", question: "What are today's top AI news stories?" },
  { category: "Science", scene: "space", icon: "rocket", question: "What has the James Webb telescope discovered recently?" },
  { category: "Finance", scene: "finance", icon: "trending-up", question: "How did the Nifty 50 move this week and why?" },
  { category: "Travel", scene: "travel", icon: "palmtree", params: { setting: "beach" }, question: "Best beaches in Goa for a quiet 3-day trip, with where to stay" },
];

export function EmptyState() {
  const { send, setPreviewScene } = useChat();
  const [items, setItems] = useState<Suggestion[]>(FALLBACK);

  useEffect(() => {
    api.suggestions().then(setItems).catch(() => {});
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pt-[12vh] text-center">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass-strong rounded-3xl px-6 py-5">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">What do you want to know?</h1>
        <p className="mt-2 text-sm text-muted">
          A ReAct search agent that reads the live web and cites every claim. The background follows your topic.
        </p>
      </motion.div>
      <div className="mt-8 grid w-full gap-2.5 sm:grid-cols-2" onMouseLeave={() => setPreviewScene(null)}>
        {items.slice(0, 8).map((s, i) => {
          const Icon = ICONS[s.icon] ?? Search;
          return (
            <motion.button
              key={s.question}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.04 * i }}
              onMouseEnter={() => setPreviewScene({ scene: s.scene, params: s.params || (s.scene === "weather" ? { condition: s.icon === "umbrella" ? "rain" : "clear", is_day: true } : {}) })}
              onFocus={() => setPreviewScene({ scene: s.scene, params: s.params || {} })}
              onClick={() => send(s.question)}
              data-testid="suggestion"
              className="glass group flex items-start gap-3 rounded-2xl p-3.5 text-left transition hover:-translate-y-0.5 hover:bg-surface-hover"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent"><Icon className="h-4 w-4" /></span>
              <span>
                <span className="block text-[11px] font-semibold uppercase tracking-wide text-subtle">{s.category}</span>
                <span className="mt-0.5 block text-sm leading-snug text-fg">{s.question}</span>
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
