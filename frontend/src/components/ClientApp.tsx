"use client";

import dynamic from "next/dynamic";

// The whole UI depends on browser-only state (localStorage client id, theme, time-based thread groups),
// so it renders on the client only. The server sends a tiny shell.
export const ClientApp = dynamic(() => import("./App").then((m) => m.App), {
  ssr: false,
  loading: () => <div className="h-dvh" style={{ background: "var(--bg)" }} />,
});
