"use client";

/**
 * The app's single store (zustand): threads, the open conversation, streaming state and the background scene.
 *
 * `send` is the heart of the UI: it appends the user message plus an empty assistant message, then applies each
 * SSE event from the backend to that assistant message as it arrives (timeline steps, sources, tokens, widgets...).
 */
import { create } from "zustand";
import { api, streamChat, type StreamEvent } from "@/lib/api";
import { guessScene } from "@/lib/scene";
import type { AssistantMeta, ChatMessage, Mode, SceneState, Source, Step, Thread } from "@/lib/types";

interface ChatState {
  threads: Thread[];                  // sidebar list, most recent first
  activeId: string | null;            // open thread (null = new chat / empty state)
  messages: ChatMessage[];            // messages of the open thread
  loadingThread: boolean;
  streaming: boolean;                 // a turn is in progress
  mode: Mode;                         // Auto / Quick / Deep toggle
  scene: SceneState;                  // background scene for the current topic
  previewScene: SceneState | null;    // temporary scene while hovering a suggestion card
  ambient: boolean;                   // user toggle: animated backgrounds on/off
  sidebarOpen: boolean;
  abort: AbortController | null;      // cancels the running stream (Stop button)

  loadThreads: () => Promise<void>;
  openThread: (id: string | null) => Promise<void>;
  send: (text: string) => Promise<void>;
  stop: () => void;
  regenerate: () => Promise<void>;
  renameThread: (id: string, title: string) => Promise<void>;
  pinThread: (id: string, pinned: boolean) => Promise<void>;
  deleteThread: (id: string) => Promise<void>;
  setMode: (m: Mode) => void;
  setPreviewScene: (s: SceneState | null) => void;
  setAmbient: (on: boolean) => void;
  setSidebar: (open: boolean) => void;
}

/** Local id for optimistic messages (replaced by server ids when the thread is reloaded). */
const uid = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Math.random()));

/**
 * Restore the scene when reopening a thread: the latest assistant message's route, refined by its weather
 * widget (today's condition, day/night) so a rainy forecast reopens as rain.
 */
function sceneFromMessages(msgs: ChatMessage[]): SceneState {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const r = msgs[i].meta?.route;
    if (msgs[i].role === "assistant" && r?.scene) {
      const weather = msgs[i].meta.widgets?.find((w) => w.type === "weather");
      const params = weather && weather.type === "weather"
        ? { condition: weather.daily?.[0]?.scene as never, is_day: weather.current.is_day, ...r.params }
        : r.params || {};
      return { scene: r.scene, params };
    }
  }
  return { scene: "default", params: {} };
}

/** Reflect the open thread in the URL (`/?t=<id>`) without a navigation, so reloads and links reopen it. */
function setUrl(id: string | null) {
  if (typeof window === "undefined") return;
  const url = id ? `/?t=${id}` : "/";
  window.history.replaceState(null, "", url);
}

export const useChat = create<ChatState>((set, get) => ({
  threads: [],
  activeId: null,
  messages: [],
  loadingThread: false,
  streaming: false,
  mode: "auto",
  scene: { scene: "default", params: {} },
  previewScene: null,
  ambient: true,
  // Start closed on phones, so the drawer doesn't cover the chat (and slide away) on every page load.
  sidebarOpen: typeof window === "undefined" ? true : window.innerWidth >= 768,
  abort: null,

  loadThreads: async () => {
    try {
      set({ threads: await api.threads() });
    } catch {
      /* backend offline: UI still works, shows an error on send */
    }
  },

  /** Open a thread (or the empty state for `null`), cancelling any stream in progress. */
  openThread: async (id) => {
    get().abort?.abort();
    setUrl(id);
    if (!id) {
      set({ activeId: null, messages: [], streaming: false, scene: { scene: "default", params: {} } });
      return;
    }
    set({ activeId: id, loadingThread: true, messages: [] });
    try {
      const msgs = await api.messages(id);
      set({ messages: msgs, loadingThread: false, scene: sceneFromMessages(msgs) });
    } catch {
      set({ loadingThread: false, activeId: null });
      setUrl(null);
    }
  },

  /** Send a message and stream the agent's reply into a new assistant message. */
  send: async (text) => {
    const q = text.trim();
    if (!q || get().streaming) return;
    const user: ChatMessage = { id: uid(), role: "user", content: q, meta: {}, created_at: new Date().toISOString() };
    const bot: ChatMessage = {
      id: uid(), role: "assistant", content: "", meta: { steps: [], all_sources: [], widgets: [], notices: [] },
      created_at: new Date().toISOString(), streaming: true,
    };
    const abort = new AbortController();
    // Optimistic UI: show both messages immediately and switch the scene from the text before the server answers.
    set((s) => ({ messages: [...s.messages, user, bot], streaming: true, abort, scene: guessScene(q), previewScene: null }));

    // Helpers that update only the assistant message being streamed (or just its meta).
    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      set((s) => ({ messages: s.messages.map((m) => (m.id === bot.id ? fn(m) : m)) }));
    const meta = (fn: (m: AssistantMeta) => AssistantMeta) => patch((m) => ({ ...m, meta: fn(m.meta) }));

    /** Apply one SSE event to the store. Event shapes are produced by backend/app/agent (see main.py's docstring). */
    const onEvent = ({ event, data }: StreamEvent) => {
      switch (event) {
        case "thread":
          // A new chat got its id: adopt it, put it in the URL and show it in the sidebar right away.
          if (!get().activeId) {
            set({ activeId: data.thread_id });
            setUrl(data.thread_id);
            const now = new Date().toISOString();
            set((s) => ({ threads: [{ id: data.thread_id, title: q.slice(0, 60), pinned: false, scene: "default", created_at: now, updated_at: now }, ...s.threads] }));
          }
          break;
        case "scene":
          // Keep params when the scene family is unchanged (e.g. weather condition refined by real data).
          set((s) => ({ scene: { scene: data.scene, params: { ...(s.scene.scene === data.scene ? s.scene.params : {}), ...data.params } } }));
          break;
        case "route":
          meta((m) => ({ ...m, route: { ...m.route, ...data } }));
          break;
        case "step":
          // Steps arrive as "running" and are later updated by id (done/failed + details): merge, don't append.
          meta((m) => {
            const steps = [...(m.steps || [])];
            const i = steps.findIndex((s) => s.id === data.id);
            if (i >= 0) steps[i] = { ...steps[i], ...data } as Step;
            else steps.push(data as Step);
            return { ...m, steps };
          });
          break;
        case "plan":
          meta((m) => ({ ...m, plan: data.todos }));
          break;
        case "source":
          meta((m) => {
            const list = [...(m.all_sources || [])];
            const i = list.findIndex((s) => s.id === data.id);
            if (i >= 0) list[i] = { ...list[i], ...data };
            else list.push(data as Source);
            return { ...m, all_sources: list };
          });
          break;
        case "widget":
          meta((m) => ({ ...m, widgets: [...(m.widgets || []), data] }));
          break;
        case "token":
          patch((m) => ({ ...m, content: m.content + data.text }));
          break;
        case "citations":
          meta((m) => ({ ...m, sources: data.sources, invalid_citations: data.invalid_removed }));
          break;
        case "followups":
          meta((m) => ({ ...m, follow_ups: data.items }));
          break;
        case "title":
          set((s) => ({ threads: s.threads.map((t) => (t.id === get().activeId ? { ...t, title: data.title } : t)) }));
          break;
        case "notice":
          meta((m) => ({ ...m, notices: [...(m.notices || []), data.message] }));
          break;
        case "error":
          meta((m) => ({ ...m, error: data.message }));
          break;
        case "done":
          // The final payload is authoritative: it replaces the streamed answer and the provisional lists.
          patch((m) => ({
            ...m,
            content: data.answer || m.content,
            streaming: false,
            meta: {
              ...m.meta, sources: data.sources, all_sources: data.all_sources, widgets: data.widgets, route: data.route, usage: data.usage,
              // steps still "running" were cut off by the research time budget
              steps: (m.meta.steps || []).map((st) => (st.status === "running" ? { ...st, status: "failed", detail: "stopped (time budget)" } : st)),
            },
          }));
          break;
      }
    };

    try {
      await streamChat({ message: q, thread_id: get().activeId, mode: get().mode }, onEvent, abort.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        meta((m) => ({ ...m, error: (err as Error).message || "Could not reach the agent. Is the backend running on :8000?" }));
      }
    } finally {
      patch((m) => ({ ...m, streaming: false }));
      // Refresh the sidebar: the server may have set a title and moved the thread to the top.
      set({ streaming: false, abort: null });
      get().loadThreads();
    }
  },

  /** Stop the current turn (the backend stops the agent when the stream disconnects). */
  stop: () => {
    get().abort?.abort();
    set({ streaming: false });
  },

  /** Drop the last exchange and ask the last user message again. */
  regenerate: async () => {
    const msgs = get().messages;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser || get().streaming) return;
    const idx = msgs.lastIndexOf(lastUser);
    set({ messages: msgs.slice(0, idx) });
    await get().send(lastUser.content);
  },

  // Thread edits are optimistic: update the list first, then tell the server (failures are ignored).
  renameThread: async (id, title) => {
    set((s) => ({ threads: s.threads.map((t) => (t.id === id ? { ...t, title } : t)) }));
    await api.rename(id, title).catch(() => {});
  },
  pinThread: async (id, pinned) => {
    set((s) => ({ threads: s.threads.map((t) => (t.id === id ? { ...t, pinned } : t)) }));
    await api.pin(id, pinned).catch(() => {});
  },
  deleteThread: async (id) => {
    set((s) => ({ threads: s.threads.filter((t) => t.id !== id) }));
    if (get().activeId === id) await get().openThread(null);
    await api.remove(id).catch(() => {});
  },

  setMode: (mode) => set({ mode }),
  setPreviewScene: (previewScene) => set({ previewScene }),
  setAmbient: (ambient) => {
    try { localStorage.setItem("rsa-ambient", ambient ? "1" : "0"); } catch {}
    set({ ambient });
  },
  setSidebar: (sidebarOpen) => set({ sidebarOpen }),
}));
