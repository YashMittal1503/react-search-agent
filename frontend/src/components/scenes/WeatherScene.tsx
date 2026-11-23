"use client";

import type { SceneParams } from "@/lib/types";
import { Particles } from "./Particles";

/**
 * Weather scene, driven by real Open-Meteo data for the place asked about: sky colour per condition and
 * day/night, sun or moon, drifting clouds, rain/snow particles, lightning flashes and fog banks.
 */

/** Sky gradients per condition, for day and night. */
const SKIES: Record<string, { day: string; night: string }> = {
  clear: { day: "linear-gradient(180deg,#2f80ed 0%,#56a8f5 45%,#a9d6ff 100%)", night: "linear-gradient(180deg,#050816 0%,#101a3d 55%,#283a6b 100%)" },
  "partly-cloudy": { day: "linear-gradient(180deg,#3b82d6 0%,#6fb0ee 50%,#bfdcf7 100%)", night: "linear-gradient(180deg,#070b1d 0%,#18234a 60%,#33436e 100%)" },
  cloudy: { day: "linear-gradient(180deg,#6b7b8f 0%,#94a3b5 55%,#c5ced8 100%)", night: "linear-gradient(180deg,#14171f 0%,#2a303c 60%,#3d4452 100%)" },
  rain: { day: "linear-gradient(180deg,#3c4a5c 0%,#5d6c80 55%,#8592a3 100%)", night: "linear-gradient(180deg,#0b0f17 0%,#1b2230 60%,#2b3445 100%)" },
  storm: { day: "linear-gradient(180deg,#1f2633 0%,#353f52 55%,#55607a 100%)", night: "linear-gradient(180deg,#05070c 0%,#121722 60%,#222a3a 100%)" },
  snow: { day: "linear-gradient(180deg,#9fb3c8 0%,#c4d3e2 55%,#eef3f8 100%)", night: "linear-gradient(180deg,#1a2233 0%,#34415a 60%,#56657e 100%)" },
  fog: { day: "linear-gradient(180deg,#a7b0ba 0%,#c3cad1 55%,#e1e5e9 100%)", night: "linear-gradient(180deg,#22262d 0%,#3a3f48 60%,#545a64 100%)" },
};

/** One SVG cloud drifting across the screen; a negative delay starts it mid-flight so the sky isn't empty at first. */
function Cloud({ top, scale, duration, delay, opacity, dark }: { top: string; scale: number; duration: number; delay: number; opacity: number; dark?: boolean }) {
  const fill = dark ? "#5b6678" : "#ffffff";
  return (
    <div className="anim-drift absolute left-0" style={{ top, animationDuration: `${duration}s`, animationDelay: `-${delay}s`, opacity }}>
      <svg width={260 * scale} height={110 * scale} viewBox="0 0 260 110" style={{ filter: "blur(2px)" }}>
        <g fill={fill}>
          <ellipse cx="80" cy="70" rx="70" ry="36" />
          <ellipse cx="135" cy="50" rx="62" ry="46" />
          <ellipse cx="190" cy="72" rx="60" ry="32" />
          <rect x="30" y="70" width="210" height="34" rx="17" />
        </g>
      </svg>
    </div>
  );
}

/** The weather background for `params.condition` and `params.is_day` (defaults: partly cloudy, day). */
export function WeatherScene({ params }: { params: SceneParams }) {
  const cond = params.condition || "partly-cloudy";
  const day = params.is_day ?? true;
  const sky = SKIES[cond] ?? SKIES["partly-cloudy"];
  const cloudCount = cond === "clear" ? 2 : cond === "partly-cloudy" ? 4 : 7;
  const darkClouds = cond === "rain" || cond === "storm" || !day;
  const showSun = day && (cond === "clear" || cond === "partly-cloudy");
  const showMoon = !day && (cond === "clear" || cond === "partly-cloudy" || cond === "cloudy");

  return (
    <div className="absolute inset-0 overflow-hidden" style={{ background: day ? sky.day : sky.night }} data-scene="weather" data-condition={cond}>
      {!day && <Particles kind="stars" density={cond === "clear" ? 1 : 0.4} />}
      {showSun && (
        <div className="absolute right-[12%] top-[10%]">
          <div className="anim-pulse-glow absolute -inset-24 rounded-full" style={{ background: "radial-gradient(circle, rgba(255,236,170,0.75) 0%, rgba(255,214,102,0.25) 40%, transparent 70%)" }} />
          <svg className="anim-spin-slow relative" width="170" height="170" viewBox="-85 -85 170 170" aria-hidden>
            {Array.from({ length: 12 }).map((_, i) => (
              <rect key={i} x="-3" y="-82" width="6" height="22" rx="3" fill="rgba(255,226,140,0.7)" transform={`rotate(${i * 30})`} />
            ))}
            <circle r="48" fill="#ffd45e" />
            <circle r="48" fill="url(#sunGrad)" />
            <defs>
              <radialGradient id="sunGrad"><stop offset="0%" stopColor="#fff3c4" /><stop offset="100%" stopColor="#ffc93c" stopOpacity="0.2" /></radialGradient>
            </defs>
          </svg>
        </div>
      )}
      {showMoon && (
        <div className="absolute right-[14%] top-[12%]">
          <div className="absolute -inset-16 rounded-full" style={{ background: "radial-gradient(circle, rgba(200,215,255,0.35), transparent 70%)" }} />
          <svg width="110" height="110" viewBox="0 0 110 110" aria-hidden>
            <circle cx="55" cy="55" r="40" fill="#e8ecf7" />
            <circle cx="72" cy="45" r="34" fill="#16214a" opacity="0.92" />
          </svg>
        </div>
      )}
      {Array.from({ length: cloudCount }).map((_, i) => (
        // Deterministic pseudo-random layout (no Math.random), so the scene doesn't reshuffle on re-render.
        <Cloud key={i} top={`${6 + ((i * 13) % 46)}%`} scale={0.7 + ((i * 37) % 10) / 10} duration={70 + i * 17} delay={i * 23} opacity={darkClouds ? 0.55 : 0.85} dark={darkClouds} />
      ))}
      {(cond === "rain" || cond === "storm") && <Particles kind="rain" density={cond === "storm" ? 1.6 : 1} />}
      {cond === "snow" && <Particles kind="snow" />}
      {cond === "storm" && <div className="anim-flash absolute inset-0 bg-white" />}
      {cond === "fog" && (
        <>
          {[20, 45, 70].map((t, i) => (
            <div key={t} className="anim-wave absolute -left-20 -right-20 h-40 rounded-full" style={{ top: `${t}%`, background: "rgba(255,255,255,0.35)", filter: "blur(30px)", animationDelay: `-${i * 3}s` }} />
          ))}
        </>
      )}
      {/* horizon haze */}
      <div className="absolute inset-x-0 bottom-0 h-1/3" style={{ background: `linear-gradient(0deg, ${day ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.25)"}, transparent)` }} />
    </div>
  );
}
