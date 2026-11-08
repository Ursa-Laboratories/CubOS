import { expect, test, type Route } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

const update = {
  current_sha: "1".repeat(40),
  latest_sha: "2".repeat(40),
  commits_behind: 2,
  update_available: true,
  checked_at: 1,
  summary: [],
  error: null,
  current_tag: null,
  latest_tag: null,
};

for (const width of [320, 1440]) {
  test(`update submission stays busy until completion and allows retry at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await installApiMocks(page);
    let applied = false;
    await page.route("**/api/v1/system/update", (route) => route.fulfill({
      json: applied
        ? { ...update, current_sha: update.latest_sha, update_available: false }
        : update,
    }));
    const submissions: Route[] = [];
    await page.route("**/api/v1/system/update/apply", (route) => { submissions.push(route); });
    await page.goto("/");

    const button = page.getByRole("button", { name: "Update & restart", exact: true });
    await button.click();
    const dialog = page.getByRole("alertdialog", { name: "Update CubOS" });
    await expect(dialog.getByRole("button", { name: "Update & restart" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(dialog).not.toBeVisible();
    await expect.poll(() => submissions.length).toBe(1);
    const busyButton = page.getByRole("button", { name: "Updating…", exact: true });
    await expect(busyButton).toBeDisabled();
    await expect(busyButton).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`update-pending-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.keyboard.press("Enter");
    await expect(dialog).not.toBeVisible();
    expect(submissions).toHaveLength(1);

    await submissions[0].fulfill({ status: 409, json: { detail: "Cannot update while a run is active" } });
    await expect(page.getByRole("status")).toContainText("Cannot update while a run is active");
    await expect(button).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath(`update-error-${width}.png`) });
    await button.click();
    await page.keyboard.press("Enter");
    await expect.poll(() => submissions.length).toBe(2);
    await expect(busyButton).toBeDisabled();
    await expect(page.getByText("Cannot update while a run is active")).not.toBeVisible();

    applied = true;
    const reloaded = page.waitForEvent("domcontentloaded");
    await submissions[1].fulfill({ json: { status: "updating", target_sha: update.latest_sha } });
    await reloaded;
    await expect(page.getByRole("heading", { name: "CubOS", exact: true })).toBeVisible();
    await expect(page.getByText(/Update available/)).not.toBeVisible();
    expect(submissions).toHaveLength(2);
    expect(state.requests.filter(request => request.method !== "GET")).toEqual([]);
  });
}

test("update confirmation supports repeated dismissal and restores keyboard focus", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const state = await installApiMocks(page);
  await page.route("**/api/v1/system/update", route => route.fulfill({ json: update }));
  await page.goto("/");
  const button = page.getByRole("button", { name: "Update & restart", exact: true });
  const dialog = page.getByRole("alertdialog", { name: "Update CubOS" });
  for (const dismiss of ["Escape", "Cancel", "backdrop"]) {
    await button.click();
    const confirm = dialog.getByRole("button", { name: "Update & restart" });
    const cancel = dialog.getByRole("button", { name: "Cancel" });
    await expect(confirm).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(cancel).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(confirm).toBeFocused();
    if (dismiss === "Escape") {
      await page.screenshot({ path: testInfo.outputPath("update-confirmation-320.png") });
      await page.keyboard.press("Escape");
    } else if (dismiss === "Cancel") {
      await cancel.click();
    } else {
      await page.mouse.click(5, 5);
    }
    await expect(dialog).not.toBeVisible();
    await expect(button).toBeFocused();
    await expect(button).toBeEnabled();
  }
  expect(state.requests.filter(request => request.method !== "GET")).toEqual([]);
});
