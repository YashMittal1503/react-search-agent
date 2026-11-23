"use client";

import { Moon, PanelLeftOpen, Sparkles, Sun } from "lucide-react";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { Toaster } from "sonner";
import { SCENE_LABEL } from "@/lib/scene";
import { useChat } from "@/store/chat";
import { AssistantMessage, UserMessage } from "./chat/Message";
import { Composer } from "./chat/Composer";
import { EmptyState } from "./chat/EmptyState";
import { CommandPalette } from "./CommandPalette";
import { SceneBackground } from "./scenes/SceneBackground";
import { Sidebar } from "./Sidebar";

// Theme lives on <html class="dark"> (set before paint by the inline script in layout.tsx).
const themeListeners = new Set<() => void>();
function subscribeTheme(cb: () => void) {
  themeListeners.add(cb);
  return () => themeListeners.delete(cb);
}
function useTheme() {
  const dark = useSyncExternalStore(subscribeTheme, () => document.documentElement.classList.contains("dark"), () => false);
  const toggle = () => {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("rsa-theme", next ? "dark" : "light"); } catch {}
    themeListeners.forEach((l) => l());
  };
  return { dark, toggle };
}

export function App() {
  const { messages, loadThreads, openThread, scene, previewScene, ambient, setAmbient, sidebarOpen, setSidebar, loadingThread, streaming } = useChat();
  const { dark, toggle } = useTheme();
  const bottom = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    loadThreads();
    const t = new URLSearchParams(window.location.search).get("t");
    if (t) openThread(t);
    try { if (localStorage.getItem("rsa-ambient") === "0") setAmbient(false); } catch {}
    if (window.innerWidth < 768) setSidebar(false);
  }, [loadThreads, openThread, setAmbient, setSidebar]);

  useEffect(() => {
    if (stick.current) bottom.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth", block: "end" });
  }, [messages, streaming]);

  const active = previewScene || scene;
  const empty = messages.length === 0 && !loadingThread;
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  return (
    <div className="relative flex h-dvh overflow-hidden text-fg">
      <SceneBackground scene={active} enabled={ambient} />
      <Sidebar />
      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 px-3 py-2.5">
          {!sidebarOpen && (
            <button onClick={() => setSidebar(true)} className="glass rounded-xl p-2 text-muted hover:text-fg" aria-label="Open sidebar"><PanelLeftOpen className="h-4 w-4" /></button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setAmbient(!ambient)} data-testid="ambient-toggle"
              className="glass flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs text-muted hover:text-fg" aria-pressed={ambient}
              title="Ambient scene backgrounds">
              <Sparkles className={`h-3.5 w-3.5 ${ambient ? "text-accent" : ""}`} />
              {ambient ? SCENE_LABEL[active.scene] : "Scenes off"}
            </button>
            <button onClick={toggle} className="glass rounded-xl p-2 text-muted hover:text-fg" aria-label="Toggle theme">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>

        <div ref={scroller} className="flex-1 overflow-y-auto thin-scroll"
          onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120; }}>
          {empty ? (
            <EmptyState />
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 pb-6 pt-2">
              {loadingThread && <div className="glass skeleton h-24 rounded-2xl" />}
              {messages.map((m) => m.role === "user" ? <UserMessage key={m.id} m={m} /> : <AssistantMessage key={m.id} m={m} last={m.id === lastAssistant} />)}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <div className="mx-auto w-full max-w-3xl px-4 pb-4">
          <Composer autoFocus />
          <p className="mt-2 text-center text-[11px] text-subtle drop-shadow-sm">Answers come from live web sources and free AI models. Check important facts.</p>
        </div>
      </main>
      <CommandPalette toggleTheme={toggle} dark={dark} />
      <Toaster position="top-center" theme={dark ? "dark" : "light"} />
    </div>
  );
}
