"use client";

import { AnimatePresence, motion } from "motion/react";
import type { SceneState } from "@/lib/types";
import { DefaultScene, FinanceScene, FoodScene, HealthScene, NewsScene, SpaceScene, SportsScene, TechScene } from "./TopicScenes";
import { TravelScene } from "./TravelScene";
import { WeatherScene } from "./WeatherScene";

function Scene({ s }: { s: SceneState }) {
  switch (s.scene) {
    case "weather": return <WeatherScene params={s.params} />;
    case "travel": return <TravelScene params={s.params} />;
    case "news": return <NewsScene />;
    case "finance": return <FinanceScene />;
    case "tech": return <TechScene />;
    case "space": return <SpaceScene />;
    case "sports": return <SportsScene />;
    case "health": return <HealthScene />;
    case "food": return <FoodScene />;
    default: return <DefaultScene />;
  }
}

/** Full-screen ambient background that follows the conversation's topic.
 *  Readability: a vignette dims the centre column, and every readable element above it is a
 *  ≥86%-opaque blurred surface, so text never sits on the artwork directly. */
export function SceneBackground({ scene, enabled }: { scene: SceneState; enabled: boolean }) {
  const s: SceneState = enabled ? scene : { scene: "default", params: {} };
  const key = `${s.scene}:${s.params.condition ?? ""}:${s.params.is_day ?? ""}:${s.params.setting ?? ""}`;
  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden data-testid="scene" data-active-scene={s.scene}>
      <AnimatePresence initial={false}>
        <motion.div key={key} className="absolute inset-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.8, ease: "easeInOut" }}>
          <Scene s={s} />
        </motion.div>
      </AnimatePresence>
      {/* vignette behind the chat column keeps glass surfaces legible on busy scenes */}
      <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse 60% 85% at 50% 50%, var(--vignette), transparent 75%)" }} />
    </div>
  );
}
