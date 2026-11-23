"use client";

/** Thread sidebar: new chat, search, threads grouped by recency, and per-thread rename / pin / delete. */
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal, PanelLeftClose, Pencil, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { Thread } from "@/lib/types";
import { useChat } from "@/store/chat";

/** Bucket threads ChatGPT-style (Pinned, Today, Yesterday, 7/30 days, Older) by last activity, in local time. */
function group(threads: Thread[]) {
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  const groups: Record<string, Thread[]> = { Pinned: [], Today: [], Yesterday: [], "Previous 7 days": [], "Previous 30 days": [], Older: [] };
  for (const t of threads) {
    const ts = new Date(t.updated_at).getTime();
    if (t.pinned) groups.Pinned.push(t);
    else if (ts >= startToday) groups.Today.push(t);
    else if (ts >= startToday - day) groups.Yesterday.push(t);
    else if (ts >= startToday - 7 * day) groups["Previous 7 days"].push(t);
    else if (ts >= startToday - 30 * day) groups["Previous 30 days"].push(t);
    else groups.Older.push(t);
  }
  return Object.entries(groups).filter(([, v]) => v.length);
}

/** One thread: click to open; the ⋯ menu renames inline (Enter saves, Escape cancels), pins or deletes. */
function ThreadRow({ t, active }: { t: Thread; active: boolean }) {
  const { openThread, renameThread, pinThread, deleteThread, setSidebar } = useChat();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(t.title);

  if (editing) {
    return (
      <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Rename chat"
        onBlur={() => { setEditing(false); if (title.trim() && title !== t.title) renameThread(t.id, title.trim()); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setTitle(t.title); setEditing(false); } }}
        className="w-full rounded-lg bg-surface-strong px-2.5 py-1.5 text-sm outline-none ring-1 ring-accent" />
    );
  }
  return (
    <div className={`group flex items-center rounded-lg ${active ? "bg-accent-soft text-fg" : "text-muted hover:bg-surface-hover hover:text-fg"}`}>
      <button onClick={() => { openThread(t.id); if (window.innerWidth < 768) setSidebar(false); }} className="min-w-0 flex-1 truncate px-2.5 py-1.5 text-left text-sm" title={t.title}>
        {t.title}
      </button>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button aria-label="Chat options" className="mr-1 rounded p-1 opacity-0 transition group-hover:opacity-100 data-[state=open]:opacity-100 focus:opacity-100">
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="start" sideOffset={4} className="glass-strong z-50 min-w-40 rounded-xl p-1 text-sm text-fg">
            <Dropdown.Item onSelect={() => setEditing(true)} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 outline-none data-[highlighted]:bg-surface-hover"><Pencil className="h-3.5 w-3.5" /> Rename</Dropdown.Item>
            <Dropdown.Item onSelect={() => pinThread(t.id, !t.pinned)} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 outline-none data-[highlighted]:bg-surface-hover">
              {t.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />} {t.pinned ? "Unpin" : "Pin"}
            </Dropdown.Item>
            <Dropdown.Item onSelect={() => { if (confirm("Delete this chat? This can't be undone.")) deleteThread(t.id); }} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-bad outline-none data-[highlighted]:bg-surface-hover"><Trash2 className="h-3.5 w-3.5" /> Delete</Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
    </div>
  );
}

/** Static column on desktop; an overlay drawer with a backdrop on phones (< 768 px). */
export function Sidebar() {
  const { threads, activeId, openThread, sidebarOpen, setSidebar } = useChat();
  const [q, setQ] = useState("");
  const groups = useMemo(() => group(threads.filter((t) => t.title.toLowerCase().includes(q.toLowerCase()))), [threads, q]);

  return (
    <>
      {sidebarOpen && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setSidebar(false)} />}
      <aside data-testid="sidebar" className={`glass-strong fixed inset-y-0 left-0 z-40 flex w-72 flex-col rounded-none border-y-0 border-l-0 transition-transform duration-300 md:static md:z-10 ${sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden"}`}>
        <div className="flex items-center gap-2 px-3 pt-3">
          <div className="flex items-center gap-2 px-1 font-semibold tracking-tight">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-accent-fg"><Search className="h-4 w-4" /></span>
            Scout
          </div>
          <button onClick={() => setSidebar(false)} className="ml-auto rounded-lg p-1.5 text-muted hover:bg-surface-hover hover:text-fg" aria-label="Close sidebar"><PanelLeftClose className="h-4 w-4" /></button>
        </div>
        <div className="space-y-2 px-3 pt-3">
          <button onClick={() => openThread(null)} data-testid="new-chat" className="flex w-full items-center gap-2 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-accent-fg transition hover:brightness-110">
            <Plus className="h-4 w-4" /> New chat <kbd className="ml-auto rounded bg-black/15 px-1.5 text-[10px]">Ctrl K</kbd>
          </button>
          <label className="flex items-center gap-2 rounded-xl bg-surface-hover px-3 py-1.5 text-sm text-muted">
            <Search className="h-3.5 w-3.5" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats" aria-label="Search chats" className="w-full bg-transparent text-fg outline-none placeholder:text-subtle" />
          </label>
        </div>
        <nav className="mt-3 flex-1 space-y-4 overflow-y-auto px-3 pb-4 thin-scroll">
          {groups.length === 0 && <p className="px-2.5 text-xs text-subtle">{q ? "No chats match." : "Your chats will appear here."}</p>}
          {groups.map(([name, list]) => (
            <div key={name}>
              <div className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-subtle">{name}</div>
              <div className="space-y-0.5">{list.map((t) => <ThreadRow key={t.id} t={t} active={t.id === activeId} />)}</div>
            </div>
          ))}
        </nav>
        <div className="border-t border-border px-4 py-3 text-[11px] leading-relaxed text-subtle">
          Runs on free model tiers · answers cite live sources
        </div>
      </aside>
    </>
  );
}
