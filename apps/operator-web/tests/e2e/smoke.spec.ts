import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

test.describe("operator app shell", () => {
  test("loads the workspace with tabs, gantry control, and deck visualization", async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "CubOS" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Gantry", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Deck", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Protocol", exact: true })).toBeVisible();
    await expect(page.getByTestId("deck-visualization")).toBeVisible();
    await expect(page.getByText("Gantry Control")).toBeVisible();
    // Settings loaded from the API populate the config directory readout.
    await expect(page.getByTitle("/data/cubos-configs")).toHaveValue("/data/cubos-configs");
  });

  test("gates the Protocol tab until gantry and deck configs are loaded", async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/");

    await page.getByRole("button", { name: "Protocol", exact: true }).click();

    await expect(page.getByText("Please load Gantry, Deck configs first.")).toBeVisible();
  });

  test("theme toggle flips the document theme and persists it", async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/");

    const initial = await page.evaluate(() => document.documentElement.dataset.theme);
    await page.getByRole("button", { name: "Toggle theme" }).click();

    const flipped = await page.evaluate(() => document.documentElement.dataset.theme);
    expect(flipped).not.toBe(initial);
    expect(await page.evaluate(() => localStorage.getItem("cubos-theme"))).toBe(flipped);
  });
});
