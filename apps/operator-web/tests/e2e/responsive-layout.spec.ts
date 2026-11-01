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
