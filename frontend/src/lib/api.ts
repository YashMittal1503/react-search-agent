/**
 * Backend client: REST calls for threads/suggestions and the SSE chat stream.
 *
 * Every request carries `X-Client-Id`, a random id stored in localStorage. There are no accounts: the backend
 * keys threads by this id, so clearing site data starts a fresh, empty history.
 */
import { createParser } from "eventsource-parser";
import type { ChatMessage, Mode, Suggestion, Thread } from "./types";

/** Backend origin (set NEXT_PUBLIC_API_URL at build time when the backend isn't on localhost:8000). */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

/**
 * Anonymous per-browser id: threads are stored server-side under it.
 * Falls back to a throwaway id when storage is blocked (private mode), so the app still works for one session.
 */
export function clientId(): string {
  if (typeof window === "undefined") return "server-render";
  try {
    let id = localStorage.getItem("rsa-client-id");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("rsa-client-id", id);
    }
    return id;
  } catch {
    return "anon-" + Math.random().toString(36).slice(2, 12);
  }
}

/** JSON request helper: adds headers, throws an Error carrying FastAPI's `detail` message on non-2xx. */
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_URL + path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId(), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** Typed wrappers for the REST endpoints (see backend/app/main.py). */
export const api = {
  threads: () => req<Thread[]>("/api/threads"),
  messages: (id: string) => req<ChatMessage[]>(`/api/threads/${id}/messages`),
  rename: (id: string, title: string) => req<Thread>(`/api/threads/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  pin: (id: string, pinned: boolean) => req<Thread>(`/api/threads/${id}`, { method: "PATCH", body: JSON.stringify({ pinned }) }),
  remove: (id: string) => req<{ ok: boolean }>(`/api/threads/${id}`, { method: "DELETE" }),
  suggestions: () => req<Suggestion[]>("/api/suggestions"),
  status: () => req<Record<string, unknown>>("/api/status"),
};

/** One SSE frame from /api/chat: the event name (step, token, scene, done...) and its JSON payload. */
export interface StreamEvent {
  event: string;
  data: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}

/**
 * POST /api/chat and parse the SSE stream, calling `onEvent` for every frame as it arrives.
 *
 * EventSource can't POST, so the stream is read with fetch + eventsource-parser. The browser's timezone and
 * locale are sent so "today" and number formats match the user. Aborting `signal` stops the request, and the
 * backend notices the disconnect and stops the agent.
 */
export async function streamChat(
  body: { message: string; thread_id?: string | null; mode: Mode },
  onEvent: (e: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(API_URL + "/api/chat", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId(), Accept: "text/event-stream" },
    body: JSON.stringify({
      ...body,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      locale: navigator.language || "en-US",
    }),
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  const parser = createParser({
    onEvent(ev) {
      if (!ev.data) return;
      try {
        onEvent({ event: ev.event || "message", data: JSON.parse(ev.data) });
      } catch {
        /* ignore keep-alive / malformed frames */
      }
    },
  });
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.feed(value);
  }
}
