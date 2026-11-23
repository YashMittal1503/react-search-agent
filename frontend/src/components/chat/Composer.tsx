"use client";

import { ArrowUp, Sparkles, Square, Wand2, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Mode } from "@/lib/types";
import { useChat } from "@/store/chat";

const MODES: { id: Mode; label: string; icon: typeof Zap; hint: string }[] = [
  { id: "auto", label: "Auto", icon: Wand2, hint: "Let the agent decide" },
  { id: "quick", label: "Quick", icon: Zap, hint: "1-3 lookups, seconds" },
  { id: "deep", label: "Deep", icon: Sparkles, hint: "Plans, subagents, minutes" },
];

export function Composer({ autoFocus }: { autoFocus?: boolean }) {
  const { send, stop, streaming, mode, setMode } = useChat();
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, [text]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "TEXTAREA" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = () => {
    if (!text.trim() || streaming) return;
    send(text);
    setText("");
  };

  return (
    <div className="glass-strong rounded-3xl p-2">
      <textarea
        ref={ref}
        value={text}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        placeholder="Ask anything — weather, news, or a deep research task…"
        aria-label="Message"
        data-testid="composer"
        className="block max-h-56 w-full resize-none overflow-y-auto bg-transparent thin-scroll px-3 pt-2 pb-1 text-[0.97rem] leading-relaxed text-fg outline-none placeholder:text-subtle"
      />
      <div className="flex items-center gap-2 px-1 pt-1">
        <div className="flex rounded-full bg-surface-hover p-0.5" role="radiogroup" aria-label="Research mode">
          {MODES.map((m) => (
            <button key={m.id} role="radio" aria-checked={mode === m.id} title={m.hint} onClick={() => setMode(m.id)}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition ${mode === m.id ? "bg-surface-strong text-fg shadow-sm" : "text-muted hover:text-fg"}`}>
              <m.icon className="h-3.5 w-3.5" /> {m.label}
            </button>
          ))}
        </div>
        <span className="ml-auto hidden text-[11px] text-subtle sm:block">Enter to send · Shift+Enter for a new line</span>
        {streaming ? (
          <button onClick={stop} aria-label="Stop" className="flex h-9 w-9 items-center justify-center rounded-full bg-fg text-bg transition hover:opacity-85">
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <button onClick={submit} disabled={!text.trim()} aria-label="Send" data-testid="send"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-accent-fg transition hover:brightness-110 disabled:opacity-35">
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
