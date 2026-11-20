import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

for (const width of [320, 390, 768, 1440]) {
  test(`workspace controls remain reachable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await installApiMocks(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "CubOS" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect(page.getByRole("button", { name: "Browse", exact: true })).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`header-${width}.png`) });
    await page.getByRole("button", { name: "Results", exact: true }).click();
    await page.getByRole("button", { name: "Workflow", exact: true }).click();
    const controls = page.locator(".operator-controls");
    await controls.scrollIntoViewIfNeeded();
    await expect(controls.getByRole("button", { name: "Advanced", exact: true })).toBeInViewport();
    await expect(controls.getByRole("button", { name: "Home", exact: true })).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`workspace-${width}.png`), fullPage: true });
    expect(state.requests.filter(r => r.method !== "GET")).toHaveLength(0);
  });
}

for (const viewport of [{ width: 390, height: 650 }, { width: 1280, height: 560 }]) {
  test(`deck modes share one viewport and keep gantry controls reachable at ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const state = await installApiMocks(page, { connected: true });
    await page.goto("/");
    await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");

    const preview = page.locator(".operator-preview");
    const deckMode = page.getByRole("group", { name: "Deck view" });
    await expect(preview.getByTestId("deck-visualization")).toBeVisible();
    await expect(deckMode.getByRole("button", { name: "2D" })).toHaveAttribute("aria-pressed", "true");
    await deckMode.getByRole("button", { name: "3D" }).click();
    if (viewport.width === 1280) {
      await expect(preview.locator(".polar-deck")).toHaveAttribute("data-state", "ready", { timeout: 30_000 });
    }

    await page.getByRole("button", { name: "Visualize", exact: true }).click();
    await expect(deckMode).toHaveCount(1);
    await expect(preview).toHaveCount(0);
    const to3D = deckMode.getByRole("button", { name: "3D" });
    await expect(to3D).toHaveAttribute("aria-pressed", "true");

    const workspace = page.locator(".operator-editor");
    const workspaceBounds = await workspace.boundingBox();
    const viewportBounds = await workspace.locator(".deck-visualization-card__viewport").boundingBox();
    expect(workspaceBounds).not.toBeNull();
    expect(viewportBounds).not.toBeNull();
    expect(viewportBounds!.height).toBeGreaterThan(180);
    expect(viewportBounds!.y + viewportBounds!.height).toBeLessThanOrEqual(workspaceBounds!.y + workspaceBounds!.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(viewport.width);

    const home = page.locator(".operator-controls").getByRole("button", { name: "Home", exact: true });
    await home.scrollIntoViewIfNeeded();
    await expect(home).toBeInViewport();
    await expect(home).toBeEnabled();
    await to3D.press("ArrowLeft");
    await to3D.press("z");
    await deckMode.getByRole("button", { name: "2D" }).click();
    await expect(page.getByTestId("deck-visualization")).toBeVisible();
    await page.getByRole("button", { name: "Workflow", exact: true }).click();
    await expect(preview.getByRole("button", { name: "2D" })).toHaveAttribute("aria-pressed", "true");
    expect(state.requests.filter((request) => request.method !== "GET")).toHaveLength(0);
  });
}

test("returns to 2D without losing Gantry Control when the CAD model is missing", async ({ page }) => {
  const state = await installApiMocks(page);
  await page.route("**/*.glb", (route) => route.fulfill({ status: 404, body: "Missing assembly" }));
  await page.goto("/");
  const assembly404 = page.waitForResponse((response) => response.url().endsWith(".glb") && response.status() === 404);
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await assembly404;
  await page.getByRole("button", { name: "Show 2D", exact: true }).click();
  await expect(page.getByTestId("deck-visualization")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gantry Control", exact: true })).toBeVisible();
  expect(state.requests.filter((request) => request.method !== "GET")).toHaveLength(0);
});
