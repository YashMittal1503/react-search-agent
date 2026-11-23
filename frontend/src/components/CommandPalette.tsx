"use client";

import { Command } from "cmdk";
import { MessageSquare, Moon, Plus, Sparkles, Sun, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { useChat } from "@/store/chat";

export function CommandPalette({ toggleTheme, dark }: { toggleTheme: () => void; dark: boolean }) {
  const [open, setOpen] = useState(false);
  const { threads, openThread, setAmbient, ambient, setMode } = useChat();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;
  const run = (fn: () => void) => () => { fn(); setOpen(false); };
  const item = "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm data-[selected=true]:bg-surface-hover";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[15vh]" onClick={() => setOpen(false)}>
      <Command className="glass-strong w-full max-w-lg overflow-hidden rounded-2xl text-fg" onClick={(e) => e.stopPropagation()} label="Command palette">
        <Command.Input autoFocus placeholder="Search chats or run a command…" className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-subtle" />
        <Command.List className="max-h-80 overflow-y-auto p-2 thin-scroll">
          <Command.Empty className="px-3 py-4 text-sm text-muted">Nothing found.</Command.Empty>
          <Command.Group heading="Actions" className="text-xs text-subtle [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1">
            <Command.Item className={item} onSelect={run(() => openThread(null))}><Plus className="h-4 w-4" /> New chat</Command.Item>
            <Command.Item className={item} onSelect={run(() => setMode("quick"))}><Zap className="h-4 w-4" /> Quick mode</Command.Item>
            <Command.Item className={item} onSelect={run(() => setMode("deep"))}><Sparkles className="h-4 w-4" /> Deep research mode</Command.Item>
            <Command.Item className={item} onSelect={run(() => setAmbient(!ambient))}><Sparkles className="h-4 w-4" /> {ambient ? "Turn off" : "Turn on"} ambient scenes</Command.Item>
            <Command.Item className={item} onSelect={run(toggleTheme)}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />} Switch to {dark ? "light" : "dark"} theme</Command.Item>
          </Command.Group>
          {threads.length > 0 && (
            <Command.Group heading="Chats" className="text-xs text-subtle [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1">
              {threads.slice(0, 30).map((t) => (
                <Command.Item key={t.id} value={t.title + " " + t.id} className={item} onSelect={run(() => openThread(t.id))}>
                  <MessageSquare className="h-4 w-4" /> <span className="truncate">{t.title}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}
