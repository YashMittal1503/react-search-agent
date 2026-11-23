// Capture README screenshots from a running app (default http://localhost:3000, real backend on :8000).
//   CLIENT_ID=<your rsa-client-id> node e2e/screenshots.mjs [threadId...]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.APP_URL || "http://localhost:3000";
const OUT = new URL("../../docs/screenshots/", import.meta.url);
mkdirSync(OUT, { recursive: true });

const shots = [
  { name: "home-light", path: "/", theme: "light" },
  { name: "scene-beach-dark", path: "/?scene=travel&setting=beach", theme: "dark" },
  { name: "scene-storm-dark", path: "/?scene=weather&condition=storm", theme: "dark" },
  { name: "scene-space-dark", path: "/?scene=space", theme: "dark" },
  ...process.argv.slice(2).map((id, i) => ({ name: `thread-${i + 1}`, path: `/?t=${id}`, theme: i % 2 ? "dark" : "light" })),
];

const browser = await chromium.launch();
for (const s of shots) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: s.theme });
  await ctx.addInitScript(([t, id]) => {
    localStorage.setItem("rsa-theme", t);
    if (id) localStorage.setItem("rsa-client-id", id); // CLIENT_ID=... to see your own threads
  }, [s.theme, process.env.CLIENT_ID || ""]);
  const page = await ctx.newPage();
  await page.goto(BASE + s.path);
  await page.waitForTimeout(s.path.includes("?t=") ? 3500 : 2000);
  await page.screenshot({ path: new URL(`${s.name}.png`, OUT).pathname.replace(/^\/([A-Za-z]:)/, "$1") });
  console.log("saved", s.name);
  await ctx.close();
}
await browser.close();
