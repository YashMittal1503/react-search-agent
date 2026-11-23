"use client";

import { useEffect, useRef } from "react";

type Kind = "rain" | "snow" | "stars" | "bubbles";

/** One particle: position, depth z (0 far .. 1 near: size, speed, opacity), speed v, size r, phase a. */
interface P { x: number; y: number; z: number; v: number; r: number; a: number }

/** Lightweight canvas particles (rain, snow, twinkling stars, bubbles).
 *  Respects prefers-reduced-motion (draws one static frame) and pauses when the tab is hidden. */
export function Particles({ kind, density = 1, color }: { kind: Kind; density?: number; color?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.classList.contains("reduce-motion");
    let w = 0, h = 0, raf = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);   // sharp on retina, capped to keep fill cost low
    let parts: P[] = [];

    /** New particle: anywhere on screen at start, otherwise just off the edge it enters from. */
    const spawn = (initial: boolean): P => {
      const z = Math.random();
      return {
        x: Math.random() * w,
        y: initial ? Math.random() * h : kind === "bubbles" ? h + 20 : -20,
        z,
        v: kind === "rain" ? 9 + z * 10 : kind === "snow" ? 0.4 + z * 1.2 : kind === "bubbles" ? 0.3 + z * 0.6 : 0,
        r: kind === "rain" ? 10 + z * 14 : kind === "snow" ? 1 + z * 2.6 : kind === "stars" ? 0.4 + z * 1.4 : 4 + z * 18,
        a: Math.random() * Math.PI * 2,
      };
    };

    /** Fit the canvas to its box and re-seed; particle count scales with screen area. */
    const resize = () => {
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const base = kind === "rain" ? 140 : kind === "snow" ? 110 : kind === "stars" ? 180 : 26;
      const n = Math.round(base * density * Math.min(1.4, (w * h) / (1400 * 800)));
      parts = Array.from({ length: n }, () => spawn(true));
    };

    /** One animation frame (t = ms timestamp, drives wobble and twinkle). */
    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const c = color || (kind === "rain" ? "rgba(200,220,255," : kind === "snow" ? "rgba(255,255,255," : kind === "stars" ? "rgba(255,255,255," : "rgba(255,255,255,");
      for (const p of parts) {
        if (kind === "rain") {
          ctx.strokeStyle = c + (0.25 + p.z * 0.35) + ")";
          ctx.lineWidth = 0.6 + p.z;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p.x - p.r * 0.18, p.y + p.r);
          ctx.stroke();
          if (!reduce) { p.y += p.v; p.x -= p.v * 0.18; }
        } else if (kind === "snow") {
          ctx.fillStyle = c + (0.5 + p.z * 0.45) + ")";
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
          ctx.fill();
          if (!reduce) { p.y += p.v; p.x += Math.sin(t / 1400 + p.a) * 0.4; }
        } else if (kind === "stars") {
          const tw = reduce ? 0.8 : 0.45 + 0.55 * Math.abs(Math.sin(t / 1600 + p.a));
          ctx.fillStyle = c + (0.25 + p.z * 0.6) * tw + ")";
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.strokeStyle = c + (0.12 + p.z * 0.18) + ")";
          ctx.lineWidth = 1.2;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
          ctx.stroke();
          if (!reduce) { p.y -= p.v; p.x += Math.sin(t / 2000 + p.a) * 0.3; }
        }
        if (p.y > h + 30 || p.y < -40 || p.x < -40) Object.assign(p, spawn(false));   // recycle off-screen particles
      }
      if (!reduce) raf = requestAnimationFrame(draw);
    };

    /** Stop drawing in background tabs (saves battery), resume when visible. */
    const onVis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(draw);
    };

    resize();
    raf = requestAnimationFrame(draw);
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [kind, density, color]);

  return <canvas ref={ref} className="absolute inset-0 h-full w-full" aria-hidden />;
}
