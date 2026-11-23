"use client";

import type { SceneParams } from "@/lib/types";
import { Particles } from "./Particles";

function Plane() {
  return (
    <div className="anim-drift absolute top-[16%]" style={{ animationDuration: "48s" }}>
      <svg width="64" height="24" viewBox="0 0 64 24" aria-hidden>
        <path d="M2 12 L40 10 L52 2 L56 2 L50 11 L62 12 L50 13 L56 22 L52 22 L40 14 Z" fill="rgba(255,255,255,0.9)" />
      </svg>
      <div className="absolute right-full top-[11px] h-[2px] w-56" style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.6))" }} />
    </div>
  );
}

function Birds() {
  return (
    <div className="anim-drift absolute top-[22%]" style={{ animationDuration: "70s", animationDelay: "-20s" }}>
      <svg width="90" height="30" viewBox="0 0 90 30" aria-hidden fill="none" stroke="rgba(30,30,50,0.55)" strokeWidth="2">
        <path d="M5 15 q6 -8 12 0 q6 -8 12 0" /><path d="M40 8 q5 -6 10 0 q5 -6 10 0" /><path d="M62 20 q4 -5 8 0 q4 -5 8 0" />
      </svg>
    </div>
  );
}

export function TravelScene({ params }: { params: SceneParams }) {
  const setting = params.setting || "city";

  if (setting === "beach") {
    return (
      <div className="absolute inset-0 overflow-hidden" data-scene="travel" style={{ background: "linear-gradient(180deg,#ff9a76 0%,#ffc58f 30%,#ffe2b8 48%,#4fb3d9 52%,#1f7fae 100%)" }}>
        <div className="absolute left-1/2 top-[34%] h-44 w-44 -translate-x-1/2 rounded-full anim-pulse-glow" style={{ background: "radial-gradient(circle,#fff4d6 0%,#ffd27a 55%,transparent 72%)" }} />
        {[54, 64, 76, 88].map((top, i) => (
          <svg key={top} className="anim-wave absolute -left-10" style={{ top: `${top}%`, animationDelay: `-${i * 2}s`, opacity: 0.35 + i * 0.12 }} width="120%" height="40" viewBox="0 0 1200 40" preserveAspectRatio="none" aria-hidden>
            <path d="M0 20 Q 75 0 150 20 T 300 20 T 450 20 T 600 20 T 750 20 T 900 20 T 1050 20 T 1200 20 V40 H0 Z" fill="rgba(255,255,255,0.28)" />
          </svg>
        ))}
        <svg className="absolute bottom-0 left-[4%] h-[55%]" viewBox="0 0 200 400" aria-hidden>
          <path d="M100 400 C 95 300 110 200 120 120" stroke="#3a2a1e" strokeWidth="10" fill="none" />
          <g fill="#1f3b2a">
            <path d="M120 120 C 80 90 40 100 10 130 C 50 105 90 110 120 125 Z" />
            <path d="M120 120 C 150 80 190 85 200 110 C 170 95 145 100 120 125 Z" />
            <path d="M120 118 C 110 70 80 50 50 50 C 85 65 105 85 120 122 Z" />
            <path d="M120 118 C 140 70 170 55 195 60 C 165 70 140 90 122 122 Z" />
          </g>
        </svg>
        <Birds />
      </div>
    );
  }

  if (setting === "mountain" || setting === "snow") {
    const snow = setting === "snow";
    return (
      <div className="absolute inset-0 overflow-hidden" data-scene="travel" style={{ background: snow ? "linear-gradient(180deg,#8fb3d9 0%,#c9dcf0 60%,#eef4fb 100%)" : "linear-gradient(180deg,#fbc2a4 0%,#f7d9c4 35%,#b7c9e2 70%,#93a9c9 100%)" }}>
        <svg className="absolute bottom-0 h-[62%] w-full" viewBox="0 0 1440 600" preserveAspectRatio="none" aria-hidden>
          <path d="M0 360 L180 200 L320 300 L520 120 L700 280 L880 160 L1080 300 L1260 180 L1440 280 V600 H0 Z" fill={snow ? "#a9bfd8" : "#8c9ec0"} opacity="0.7" />
          <path d="M520 120 L470 165 L500 160 L520 175 L545 158 L575 170 Z M880 160 L840 195 L870 190 L885 204 L905 188 L930 196 Z" fill="#ffffff" opacity="0.9" />
          <path d="M0 450 L200 300 L380 420 L600 260 L820 420 L1040 300 L1240 420 L1440 330 V600 H0 Z" fill={snow ? "#7f98b6" : "#62789c"} opacity="0.85" />
          <path d="M0 540 L240 430 L480 520 L760 420 L1000 530 L1240 450 L1440 520 V600 H0 Z" fill={snow ? "#e9f0f8" : "#3e5272"} />
        </svg>
        {snow ? <Particles kind="snow" density={0.8} /> : <Birds />}
      </div>
    );
  }

  if (setting === "desert") {
    return (
      <div className="absolute inset-0 overflow-hidden" data-scene="travel" style={{ background: "linear-gradient(180deg,#f6b26b 0%,#f9d29d 45%,#f3c178 100%)" }}>
        <div className="absolute right-[18%] top-[14%] h-36 w-36 rounded-full anim-pulse-glow" style={{ background: "radial-gradient(circle,#fff6da 0%,#ffcf73 60%,transparent 72%)" }} />
        <svg className="absolute bottom-0 h-1/2 w-full" viewBox="0 0 1440 500" preserveAspectRatio="none" aria-hidden>
          <path d="M0 260 C 300 160 520 300 820 220 C 1060 160 1260 250 1440 200 V500 H0 Z" fill="#e39a4f" opacity="0.8" />
          <path d="M0 360 C 260 290 560 400 860 330 C 1120 270 1300 360 1440 320 V500 H0 Z" fill="#cf7f3a" />
        </svg>
      </div>
    );
  }

  if (setting === "countryside") {
    return (
      <div className="absolute inset-0 overflow-hidden" data-scene="travel" style={{ background: "linear-gradient(180deg,#8ec5fc 0%,#cfe7ff 55%,#e0f2d8 100%)" }}>
        <svg className="absolute bottom-0 h-1/2 w-full" viewBox="0 0 1440 500" preserveAspectRatio="none" aria-hidden>
          <path d="M0 260 C 320 160 640 320 960 220 C 1180 150 1320 230 1440 200 V500 H0 Z" fill="#9cc98a" />
          <path d="M0 360 C 300 280 700 420 1040 330 C 1240 280 1360 330 1440 320 V500 H0 Z" fill="#6fa95c" />
        </svg>
        <Birds />
      </div>
    );
  }

  // city: golden-hour skyline
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene="travel" style={{ background: "linear-gradient(180deg,#2b2d5c 0%,#7a4b8c 35%,#f08a5d 70%,#ffc38a 100%)" }}>
      <div className="absolute left-[60%] top-[48%] h-48 w-48 rounded-full anim-pulse-glow" style={{ background: "radial-gradient(circle,#fff0c9 0%,#ffb36b 55%,transparent 72%)" }} />
      <svg className="absolute bottom-0 h-[45%] w-full" viewBox="0 0 1440 450" preserveAspectRatio="none" aria-hidden>
        <path fill="#3b2a4f" opacity="0.7" d="M0 450 V250 h60 v-60 h40 v90 h50 v-140 h30 v-30 h20 v30 h30 v170 h60 v-90 h70 v120 h40 v-200 l25 -40 l25 40 v200 h60 v-110 h80 v140 h50 v-180 h40 v180 h70 v-80 h60 v100 h50 v-150 h30 v-20 h30 v170 h70 v-110 h60 v130 h40 v-90 h70 v120 V450 Z" />
        <path fill="#1f1830" d="M0 450 V320 h80 v-50 h60 v70 h90 v-100 h40 v100 h70 v-60 h80 v90 h60 v-130 h50 v130 h90 v-70 h60 v80 h70 v-110 h40 v110 h90 v-60 h70 v90 h60 v-80 h80 v100 V450 Z" />
      </svg>
      <Plane />
    </div>
  );
}
