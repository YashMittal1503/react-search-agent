"use client";

import { Cloud, CloudFog, CloudLightning, CloudRain, CloudSun, Droplets, Moon, Snowflake, Sun, Wind } from "lucide-react";
import { useState } from "react";
import type { NewsWidget, WeatherWidget, Widget } from "@/lib/types";
import { Favicon, formatDate } from "./Citation";

/** Rich cards attached to an answer: live weather (Open-Meteo) and recent news articles. */

/** Weather condition -> icon (clear shows a moon at night). */
function CondIcon({ scene, day = true, className }: { scene: string; day?: boolean; className?: string }) {
  const c = className || "h-5 w-5";
  switch (scene) {
    case "clear": return day ? <Sun className={`${c} text-amber-500`} /> : <Moon className={`${c} text-indigo-300`} />;
    case "partly-cloudy": return <CloudSun className={`${c} text-amber-500`} />;
    case "rain": return <CloudRain className={`${c} text-sky-500`} />;
    case "storm": return <CloudLightning className={`${c} text-violet-500`} />;
    case "snow": return <Snowflake className={`${c} text-sky-300`} />;
    case "fog": return <CloudFog className={`${c} text-slate-400`} />;
    default: return <Cloud className={`${c} text-slate-400`} />;
  }
}

type Unit = "C" | "F";
const f = (c: number) => Math.round(c * 9 / 5 + 32);   // °C -> °F
const UNIT_KEY = "rsa-temp-unit";
// IANA zones in the US (plus its territories that use °F). Matched as prefixes.
const US_ZONES = /^(America\/(New_York|Chicago|Denver|Phoenix|Los_Angeles|Anchorage|Juneau|Sitka|Metlakatla|Nome|Yakutat|Adak|Boise|Detroit|Indiana|Kentucky|Menominee|North_Dakota)|Pacific\/(Honolulu|Guam|Saipan|Pago_Pago)|America\/Puerto_Rico)/;

/**
 * Which unit to show. An explicit choice (the °C/°F toggle) is remembered; otherwise °F only for viewers whose
 * timezone is in the US. The browser language is NOT used: "en-US" is the default on most machines worldwide,
 * which made Delhi's 19 °C show up as a bare "67°".
 */
function initialUnit(): Unit {
  try {
    const saved = localStorage.getItem(UNIT_KEY);
    if (saved === "C" || saved === "F") return saved;
  } catch {}
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  return US_ZONES.test(tz) ? "F" : "C";
}

/** Current conditions, the next 12 hours and a 5-day strip. Times are local to the place, not the viewer. */
function WeatherCard({ w }: { w: WeatherWidget }) {
  const [unit, setUnit] = useState<Unit>(initialUnit);
  const choose = (u: Unit) => {
    setUnit(u);
    try { localStorage.setItem(UNIT_KEY, u); } catch {}
  };
  // Small numbers carry just "°"; the big reading and the toggle always name the unit, so it's never ambiguous.
  const t = (c: number) => `${unit === "F" ? f(c) : Math.round(c)}°`;
  const today = w.daily[0];
  const place = [w.location.name, w.location.admin1, w.location.country].filter(Boolean).join(", ");
  return (
    <div className="glass rounded-2xl p-4" data-testid="weather-widget">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm text-muted">
            {place}
            {w.location.approximate && w.location.requested && <span className="text-subtle"> · nearest to {w.location.requested}</span>}
          </div>
          <div className="mt-1 flex items-center gap-3">
            <CondIcon scene={w.scene?.condition || today?.scene || "cloudy"} day={w.current.is_day} className="h-10 w-10" />
            <span className="text-5xl font-semibold tracking-tight" data-testid="weather-temp">
              {t(w.current.temperature_c)}<span className="align-top text-2xl font-medium text-muted">{unit}</span>
            </span>
            <div className="text-sm leading-tight">
              <div className="font-medium">{w.current.condition}</div>
              <div className="text-muted">Feels like {t(w.current.feels_like_c)}</div>
            </div>
          </div>
        </div>
        <div className="space-y-1 text-right text-xs text-muted">
          <div className="ml-auto flex w-fit rounded-full bg-surface-hover p-0.5" role="radiogroup" aria-label="Temperature unit">
            {(["C", "F"] as const).map((u) => (
              <button key={u} role="radio" aria-checked={unit === u} onClick={() => choose(u)}
                className={`rounded-full px-2 py-0.5 font-medium ${unit === u ? "bg-surface-strong text-fg shadow-sm" : "hover:text-fg"}`}>°{u}</button>
            ))}
          </div>
          {today && <div>H {t(today.max_c)} · L {t(today.min_c)}</div>}
          <div className="flex items-center justify-end gap-1"><Droplets className="h-3 w-3" /> {w.current.humidity}%</div>
          <div className="flex items-center justify-end gap-1"><Wind className="h-3 w-3" /> {Math.round(w.current.wind_kmh)} km/h</div>
        </div>
      </div>
      <div className="mt-4 flex gap-3 overflow-x-auto pb-1 thin-scroll">
        {w.hourly.slice(0, 12).map((h) => (
          <div key={h.time} className="flex w-12 shrink-0 flex-col items-center gap-1 text-xs">
            <span className="text-muted">{h.time.slice(11, 16)}</span>
            <CondIcon scene={h.condition} day={h.is_day ?? true} className="h-4 w-4" />
            <span className="font-medium">{t(h.temperature_c)}</span>
            {h.precip_prob != null && h.precip_prob > 0 && <span className="text-[10px] text-sky-500">{h.precip_prob}%</span>}
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
        {w.daily.slice(0, 5).map((d) => (
          <div key={d.date} className="flex items-center gap-2 rounded-xl bg-surface-hover px-2.5 py-2 text-xs sm:flex-col sm:gap-1">
            {/* Noon, so the weekday can't shift by a day across time zones. */}
            <span className="w-10 text-muted sm:w-auto">{new Date(d.date + "T12:00").toLocaleDateString(undefined, { weekday: "short" })}</span>
            <CondIcon scene={d.scene} className="h-4 w-4" />
            <span><span className="font-medium">{t(d.max_c)}</span> <span className="text-muted">{t(d.min_c)}</span></span>
            {d.precip_prob > 0 && <span className="text-[10px] text-sky-500">{d.precip_prob}%</span>}
          </div>
        ))}
      </div>
      <div className="mt-2 text-[10px] text-subtle">Live data · Open-Meteo</div>
    </div>
  );
}

/** Up to 4 article cards from a news search. */
function NewsCards({ w }: { w: NewsWidget }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2" data-testid="news-widget">
      {w.items.slice(0, 4).map((n) => (
        <a key={n.url} href={n.url} target="_blank" rel="noopener noreferrer" className="glass rounded-xl p-3 text-sm transition hover:-translate-y-0.5 hover:bg-surface-hover">
          <div className="flex items-center gap-1.5 text-xs text-muted">
            <Favicon domain={n.domain} size={14} /> <span className="truncate">{n.domain}</span>
            {n.published && <span className="ml-auto shrink-0">{formatDate(n.published)}</span>}
          </div>
          <div className="mt-1 line-clamp-2 font-medium leading-snug">{n.title}</div>
        </a>
      ))}
    </div>
  );
}

/** Render the latest widget of each type (an agent may call the same tool more than once). */
export function Widgets({ widgets }: { widgets: Widget[] }) {
  const weather = widgets.filter((w): w is WeatherWidget => w.type === "weather").slice(-1);
  const news = widgets.filter((w): w is NewsWidget => w.type === "news").slice(-1);
  return (
    <>
      {weather.map((w, i) => <WeatherCard key={"w" + i} w={w} />)}
      {news.map((w, i) => <NewsCards key={"n" + i} w={w} />)}
    </>
  );
}
