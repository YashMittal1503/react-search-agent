"use client";

/**
 * Backgrounds for non-weather topics. Each is pure CSS/SVG (plus canvas particles where noted) and stays
 * subtle: the chat sits on glass above it, and the e2e contrast tests check every scene in both themes.
 */
import { Particles } from "./Particles";

/** Newsprint columns with scrolling section headlines. */
export function NewsScene() {
  const headlines = ["BREAKING", "MARKETS", "WORLD", "TECHNOLOGY", "SCIENCE", "SPORTS", "CLIMATE", "POLITICS", "CULTURE", "HEALTH"];
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="news"
      style={{ background: "linear-gradient(180deg,#f3efe6 0%,#e9e2d3 100%)" }}>
      <div className="absolute inset-0 opacity-60 dark:opacity-30" style={{
        backgroundImage: "repeating-linear-gradient(90deg, transparent 0 calc(25% - 1px), rgba(60,50,30,0.15) calc(25% - 1px) 25%), repeating-linear-gradient(0deg, rgba(60,50,30,0.07) 0 2px, transparent 2px 18px)",
      }} />
      <div className="absolute left-[4%] top-[6%] select-none font-serif text-[16vw] font-black leading-none tracking-tighter text-[rgba(40,32,20,0.07)]">THE DAILY</div>
      <div className="absolute inset-x-0 bottom-0 overflow-hidden bg-[#b91c1c]/85 py-2">
        <div className="anim-ticker flex w-max gap-10 whitespace-nowrap text-sm font-semibold tracking-widest text-white/90">
          {[...headlines, ...headlines, ...headlines, ...headlines].map((h, i) => <span key={i}>● {h}</span>)}
        </div>
      </div>
      <div className="absolute inset-0 hidden dark:block" style={{ background: "rgba(10,10,14,0.72)" }} />
    </div>
  );
}

/** Flowing chart lines over a dark trading-floor gradient. */
export function FinanceScene() {
  const lines = [
    { d: "M0 420 L120 380 L240 400 L360 300 L480 330 L600 240 L720 270 L840 180 L960 220 L1080 140 L1200 170 L1320 90 L1440 120", c: "#34d399" },
    { d: "M0 300 L120 330 L240 280 L360 350 L480 310 L600 380 L720 340 L840 400 L960 360 L1080 420 L1200 390 L1320 450 L1440 430", c: "#f87171" },
    { d: "M0 500 L160 470 L320 480 L480 430 L640 450 L800 390 L960 410 L1120 350 L1280 370 L1440 320", c: "#60a5fa" },
  ];
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="finance" style={{ background: "radial-gradient(ellipse at 70% 20%,#16213e 0%,#0b1020 70%)" }}>
      <div className="absolute inset-0" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)", backgroundSize: "60px 60px" }} />
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1440 600" preserveAspectRatio="none" aria-hidden>
        {lines.map((l, i) => (
          <path key={i} d={l.d} fill="none" stroke={l.c} strokeWidth="2.5" strokeOpacity="0.55" strokeDasharray="2400" strokeDashoffset="2400"
            style={{ animation: `dash ${8 + i * 3}s ease-out ${i * 0.8}s forwards` }} />
        ))}
        {Array.from({ length: 24 }).map((_, i) => {
          const up = (i * 7) % 3 !== 0;
          const x = 40 + i * 58, h = 20 + ((i * 37) % 60), y = 470 - ((i * 53) % 120);
          return <rect key={i} x={x} y={y} width="14" height={h} fill={up ? "#34d399" : "#f87171"} opacity="0.18" rx="2" />;
        })}
      </svg>
    </div>
  );
}

/** Circuit-board grid with travelling signal pulses. */
export function TechScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="tech" style={{ background: "radial-gradient(ellipse at 30% 10%,#1b1e3d 0%,#07080f 70%)" }}>
      <svg className="absolute inset-0 h-full w-full opacity-60" aria-hidden>
        <defs>
          <pattern id="circuit" width="120" height="120" patternUnits="userSpaceOnUse">
            <path d="M0 60 H40 L60 40 H120 M60 0 V30 M60 90 V120 M90 60 V90 H120" stroke="rgba(129,140,248,0.22)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="60" r="3" fill="rgba(129,140,248,0.45)" />
            <circle cx="60" cy="30" r="3" fill="rgba(56,189,248,0.45)" />
            <circle cx="90" cy="90" r="3" fill="rgba(129,140,248,0.45)" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#circuit)" />
      </svg>
      {[[15, 20], [70, 30], [40, 70], [85, 75], [25, 55]].map(([x, y], i) => (
        <div key={i} className="anim-pulse-glow absolute h-56 w-56 rounded-full" style={{ left: `${x}%`, top: `${y}%`, animationDelay: `-${i * 1.3}s`, background: i % 2 ? "radial-gradient(circle,rgba(56,189,248,0.25),transparent 65%)" : "radial-gradient(circle,rgba(129,140,248,0.3),transparent 65%)" }} />
      ))}
    </div>
  );
}

/** Starfield (canvas) with nebula glows, for science and astronomy. */
export function SpaceScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="space" style={{ background: "radial-gradient(ellipse at 20% 80%,#2a1446 0%,#0a0820 45%,#02030a 100%)" }}>
      <Particles kind="stars" density={1.3} />
      <div className="anim-aurora absolute -left-1/4 top-0 h-[70%] w-[80%] rounded-full opacity-40" style={{ background: "radial-gradient(circle,rgba(168,85,247,0.35),transparent 60%)", filter: "blur(40px)" }} />
      <div className="anim-float absolute right-[10%] top-[14%]">
        <svg width="220" height="220" viewBox="-110 -110 220 220" aria-hidden>
          <defs>
            <radialGradient id="planet" cx="35%" cy="35%"><stop offset="0%" stopColor="#fbbf77" /><stop offset="70%" stopColor="#c2410c" /><stop offset="100%" stopColor="#431407" /></radialGradient>
          </defs>
          <ellipse rx="105" ry="24" fill="none" stroke="rgba(253,230,138,0.45)" strokeWidth="6" transform="rotate(-18)" />
          <circle r="62" fill="url(#planet)" />
          <path d="M -100 18 A 105 24 0 0 0 100 -18" fill="none" stroke="rgba(253,230,138,0.6)" strokeWidth="6" transform="rotate(-18)" />
        </svg>
      </div>
    </div>
  );
}

/** Stadium floodlights over a pitch. */
export function SportsScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="sports" style={{ background: "linear-gradient(180deg,#0b1a2e 0%,#12304a 45%,#1d6b3a 46%,#15532c 100%)" }}>
      {[12, 50, 88].map((x, i) => (
        <div key={x} className="anim-pulse-glow absolute top-[-6%] h-72 w-72 -translate-x-1/2 rounded-full" style={{ left: `${x}%`, animationDelay: `-${i}s`, background: "radial-gradient(circle,rgba(255,255,230,0.55),transparent 65%)" }} />
      ))}
      <svg className="absolute bottom-0 h-[54%] w-full" viewBox="0 0 1440 500" preserveAspectRatio="none" aria-hidden>
        {Array.from({ length: 8 }).map((_, i) => (
          <rect key={i} x={i * 180} y="0" width="90" height="500" fill="rgba(255,255,255,0.04)" />
        ))}
        <g stroke="rgba(255,255,255,0.5)" strokeWidth="3" fill="none">
          <rect x="120" y="60" width="1200" height="400" />
          <line x1="720" y1="60" x2="720" y2="460" />
          <circle cx="720" cy="260" r="80" />
          <rect x="120" y="170" width="140" height="180" />
          <rect x="1180" y="170" width="140" height="180" />
        </g>
      </svg>
    </div>
  );
}

/** Calm, slowly breathing gradients with rising bubbles. */
export function HealthScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="health" style={{ background: "linear-gradient(160deg,#d9f5ec 0%,#e8f4fb 55%,#f3ecfb 100%)" }}>
      {[[10, 20, 320], [65, 10, 260], [30, 60, 380], [80, 60, 300]].map(([x, y, s], i) => (
        <div key={i} className="anim-pulse-glow absolute rounded-full" style={{ left: `${x}%`, top: `${y}%`, width: s, height: s, animationDuration: `${8 + i * 2}s`, background: i % 2 ? "radial-gradient(circle,rgba(16,185,129,0.25),transparent 65%)" : "radial-gradient(circle,rgba(56,189,248,0.25),transparent 65%)" }} />
      ))}
      <svg className="absolute left-0 top-1/2 h-24 w-full -translate-y-1/2 opacity-40" viewBox="0 0 1440 100" preserveAspectRatio="none" aria-hidden>
        <path d="M0 50 H500 L530 50 L550 15 L575 85 L600 30 L620 50 H1440" stroke="#10b981" strokeWidth="3" fill="none" strokeDasharray="1600" strokeDashoffset="1600" style={{ animation: "dash 6s ease-out forwards" }} />
      </svg>
      <div className="absolute inset-0 hidden dark:block" style={{ background: "rgba(8,14,16,0.75)" }} />
      <Particles kind="bubbles" density={0.6} color="rgba(16,185,129," />
    </div>
  );
}

/** Warm kitchen tones. */
export function FoodScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="food" style={{ background: "linear-gradient(170deg,#fff1e0 0%,#ffd9b3 55%,#f9b98a 100%)" }}>
      {[[20, 30], [75, 25], [55, 70]].map(([x, y], i) => (
        <div key={i} className="anim-pulse-glow absolute h-80 w-80 rounded-full" style={{ left: `${x}%`, top: `${y}%`, animationDelay: `-${i * 2}s`, background: "radial-gradient(circle,rgba(251,146,60,0.3),transparent 65%)" }} />
      ))}
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={i} className="anim-rise absolute bottom-[8%] h-28 w-10 rounded-full" style={{ left: `${12 + i * 12}%`, animationDelay: `-${i * 1.3}s`, background: "linear-gradient(0deg,rgba(255,255,255,0.0),rgba(255,255,255,0.55))", filter: "blur(10px)" }} />
      ))}
      <div className="absolute inset-0 hidden dark:block" style={{ background: "rgba(20,12,6,0.72)" }} />
    </div>
  );
}

/** Aurora: the neutral default for general questions and chitchat. */
export function DefaultScene() {
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="default" style={{ background: "var(--bg)" }}>
      <div className="anim-aurora absolute -left-[15%] -top-[20%] h-[70vh] w-[70vw] rounded-full opacity-50 dark:opacity-35" style={{ background: "radial-gradient(circle,rgba(99,102,241,0.45),transparent 62%)", filter: "blur(50px)" }} />
      <div className="anim-aurora absolute -right-[10%] top-[30%] h-[60vh] w-[55vw] rounded-full opacity-40 dark:opacity-30" style={{ animationDelay: "-8s", background: "radial-gradient(circle,rgba(236,72,153,0.38),transparent 62%)", filter: "blur(60px)" }} />
      <div className="anim-aurora absolute bottom-[-25%] left-[25%] h-[55vh] w-[50vw] rounded-full opacity-40 dark:opacity-30" style={{ animationDelay: "-14s", background: "radial-gradient(circle,rgba(20,184,166,0.38),transparent 62%)", filter: "blur(60px)" }} />
    </div>
  );
}
