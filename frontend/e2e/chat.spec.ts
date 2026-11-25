import { expect, test } from "@playwright/test";
import { mockBackend } from "./mock";

test.beforeEach(async ({ page }) => mockBackend(page));

test("empty state shows suggestions and hovering previews the scene", async ({ page }) => {
  await page.goto("/");
  const cards = page.getByTestId("suggestion");
  await expect(cards.first()).toBeVisible();
  await cards.filter({ hasText: "Kyoto" }).first().hover();
  await expect(page.getByTestId("scene")).toHaveAttribute("data-active-scene", "travel");
});

test("a weather question streams an answer with citations, widget and weather scene", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("composer").fill("What's the weather in Mumbai today?");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("weather-widget")).toBeVisible();
  await expect(page.getByTestId("scene")).toHaveAttribute("data-active-scene", "weather");
  await expect(page.locator('[data-scene="weather"][data-condition="rain"]')).toBeVisible();
  const chip = page.getByTestId("citation").first();
  await expect(chip).toHaveAttribute("href", /open-meteo\.com/);
  await expect(page.getByTestId("followups")).toContainText("Will it rain tomorrow?");
  await expect(page).toHaveURL(/\?t=t-1/);
});

test("ambient scenes can be switched off", async ({ page }) => {
  await page.goto("/?scene=space");
  await expect(page.getByTestId("scene")).toHaveAttribute("data-active-scene", "space");
  await page.getByTestId("ambient-toggle").click();
  await expect(page.getByTestId("scene")).toHaveAttribute("data-active-scene", "default");
});

// Regression: an en-US browser in India used to get a bare "88°" (°F). Unit now follows the timezone, is
// always labelled, and the user's toggle choice is remembered.
test.describe("temperature unit", () => {
  test.use({ locale: "en-US", timezoneId: "Asia/Kolkata" });

  test("defaults to °C outside the US and can be toggled to °F", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("composer").fill("What's the weather in Mumbai today?");
    await page.getByTestId("send").click();
    const temp = page.getByTestId("weather-temp");
    await expect(temp).toHaveText("31°C");                     // mock: 31.2 °C
    await page.getByRole("radio", { name: "°F" }).click();
    await expect(temp).toHaveText("88°F");
    await page.reload();                                       // choice persists (thread reload isn't mocked; check storage)
    expect(await page.evaluate(() => localStorage.getItem("rsa-temp-unit"))).toBe("F");
  });
});
