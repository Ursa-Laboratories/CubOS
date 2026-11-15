import { expect, test, type Page, type Route } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

async function mockDirectoryPicker(page: Page) {
  const state = await installApiMocks(page);
  await page.route("**/api/v1/settings/browse", route => route.fulfill({
    status: 503, json: { detail: "No display" },
  }));
  const submissions: Route[] = [];
  await page.route("**/api/v1/settings", route => {
    if (route.request().method() === "PUT") submissions.push(route);
    else return route.fulfill({ json: { config_dir: "/data/cubos-configs" } });
  });
  return { state, submissions };
}

for (const width of [320, 1440]) {
  test(`directory submission stays pending, reports failure, and retries at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, submissions } = await mockDirectoryPicker(page);
    await page.goto("/");
    const browse = page.getByRole("button", { name: "Browse", exact: true });
    await browse.click();
    const dialog = page.getByRole("dialog", { name: "Select config directory" });
    const input = dialog.getByRole("textbox");
    await input.fill("/missing");
    await page.keyboard.press("Enter");
    await expect.poll(() => submissions.length).toBe(1);
    await page.keyboard.press("Enter");
    await page.screenshot({ path: testInfo.outputPath(`directory-pending-${width}.png`) });
    expect(submissions).toHaveLength(1);
    await expect(input).toHaveAttribute("readonly", "");
    await expect(dialog.getByRole("button", { name: "Applying…" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await page.mouse.click(5, 5);
    await expect(dialog).toBeVisible();
    await input.focus();
    await page.keyboard.press("Tab");
    await expect(input).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(input).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);

    await submissions[0].fulfill({ status: 400, json: { detail: "Directory does not exist" } });
    await expect(dialog.getByRole("alert")).toContainText("Directory does not exist");
    await expect(input).toBeEditable();
    await input.fill("/data/new-configs");
    await dialog.getByRole("button", { name: "Use Directory" }).click();
    await expect.poll(() => submissions.length).toBe(2);
    await expect(dialog.getByRole("alert")).toHaveCount(0);
    await submissions[1].fulfill({ json: { config_dir: "/data/new-configs" } });
    await expect(dialog).not.toBeVisible();
    await expect(browse).toBeFocused();
    await expect(page.getByTitle("/data/new-configs")).toHaveValue("/data/new-configs");
    await page.screenshot({ path: testInfo.outputPath(`directory-saved-${width}.png`) });
    expect(state.requests.filter(request => request.method !== "GET")).toEqual([]);
  });
}

test("declining discard keeps the directory path and edits available for a later choice", async ({ page }, testInfo) => {
  const { submissions } = await mockDirectoryPicker(page);
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await expect(page.getByLabel("Serial port", { exact: true })).toHaveValue("/dev/ttyUSB0");
  await page.getByLabel("Serial port", { exact: true }).fill("/mock/edited-port");
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Select config directory" });
  const input = dialog.getByRole("textbox");
  await input.fill("/data/new-configs");
  await dialog.getByRole("button", { name: "Use Directory" }).click();
  const confirmation = page.getByRole("alertdialog", { name: "Discard changes?" });
  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await expect(confirmation).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("directory-discard-declined.png") });
  await expect(dialog).toBeVisible();
  await expect(input).toHaveValue("/data/new-configs");
  await expect(input).toBeFocused();
  expect(submissions).toHaveLength(0);
  await expect(page.locator("#gantry-serial-port")).toHaveValue("/mock/edited-port");
  await dialog.getByRole("button", { name: "Use Directory" }).click();
  await confirmation.getByRole("button", { name: "Discard", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  await submissions[0].fulfill({ json: { config_dir: "/data/new-configs" } });
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel("Gantry config", { exact: true })).toHaveValue("");
});
