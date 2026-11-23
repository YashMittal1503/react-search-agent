"use client";

import { Cloud, CloudFog, CloudLightning, CloudRain, CloudSun, Droplets, Moon, Snowflake, Sun, Wind } from "lucide-react";
import type { NewsWidget, WeatherWidget, Widget } from "@/lib/types";
import { Favicon, formatDate } from "./Citation";

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

const f = (c: number) => Math.round(c * 9 / 5 + 32);
const useF = () => typeof navigator !== "undefined" && navigator.language === "en-US";

function WeatherCard({ w }: { w: WeatherWidget }) {
  const fahrenheit = useF();
  const t = (c: number) => (fahrenheit ? `${f(c)}°` : `${Math.round(c)}°`);
  const today = w.daily[0];
  const place = [w.location.name, w.location.admin1, w.location.country].filter(Boolean).join(", ");
  return (
    <div className="glass rounded-2xl p-4" data-testid="weather-widget">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm text-muted">{place}</div>
          <div className="mt-1 flex items-center gap-3">
            <CondIcon scene={today?.scene || "cloudy"} day={w.current.is_day} className="h-10 w-10" />
            <span className="text-5xl font-semibold tracking-tight">{t(w.current.temperature_c)}</span>
            <div className="text-sm leading-tight">
              <div className="font-medium">{w.current.condition}</div>
              <div className="text-muted">Feels like {t(w.current.feels_like_c)}</div>
            </div>
          </div>
        </div>
        <div className="space-y-1 text-right text-xs text-muted">
          {today && <div>H {t(today.max_c)} · L {t(today.min_c)}</div>}
          <div className="flex items-center justify-end gap-1"><Droplets className="h-3 w-3" /> {w.current.humidity}%</div>
          <div className="flex items-center justify-end gap-1"><Wind className="h-3 w-3" /> {Math.round(w.current.wind_kmh)} km/h</div>
        </div>
      </div>
      <div className="mt-4 flex gap-3 overflow-x-auto pb-1 thin-scroll">
        {w.hourly.slice(0, 12).map((h) => (
          <div key={h.time} className="flex w-12 shrink-0 flex-col items-center gap-1 text-xs">
            <span className="text-muted">{h.time.slice(11, 16)}</span>
            <CondIcon scene={h.condition} className="h-4 w-4" />
            <span className="font-medium">{t(h.temperature_c)}</span>
            {h.precip_prob != null && h.precip_prob > 0 && <span className="text-[10px] text-sky-500">{h.precip_prob}%</span>}
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
        {w.daily.slice(0, 5).map((d) => (
          <div key={d.date} className="flex items-center gap-2 rounded-xl bg-surface-hover px-2.5 py-2 text-xs sm:flex-col sm:gap-1">
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
