import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockBackend } from "./mock";

// Every scene x theme must keep text at WCAG AA contrast: text sits on glass surfaces, never on the art.
const SCENES = [
  "scene=default", "scene=weather&condition=clear", "scene=weather&condition=clear&day=0", "scene=weather&condition=rain",
  "scene=weather&condition=storm", "scene=weather&condition=snow", "scene=weather&condition=fog",
  "scene=travel&setting=city", "scene=travel&setting=beach", "scene=travel&setting=mountain", "scene=travel&setting=desert",
  "scene=news", "scene=finance", "scene=tech", "scene=space", "scene=sports", "scene=health", "scene=food",
];

for (const theme of ["light", "dark"] as const) {
  for (const q of SCENES) {
    test(`contrast: ${q} (${theme})`, async ({ page }) => {
      await mockBackend(page);
      await page.emulateMedia({ reducedMotion: "reduce", colorScheme: theme });
      await page.addInitScript((t) => localStorage.setItem("rsa-theme", t), theme);
      await page.goto(`/?${q}`);
      await expect(page.getByTestId("suggestion").first()).toBeVisible();
      await page.waitForTimeout(900); // scene crossfade
      const results = await new AxeBuilder({ page }).withRules(["color-contrast"]).include("main").analyze();
      const issues = results.violations.flatMap((v) => v.nodes.map((n) => `${n.target.join(" ")}: ${n.failureSummary}`));
      expect(issues, issues.join("\n")).toEqual([]);
    });
  }
}
