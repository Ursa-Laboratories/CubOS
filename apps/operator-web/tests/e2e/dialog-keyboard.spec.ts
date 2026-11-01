import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

test("confirmation contains forward and reverse tabbing and restores its trigger", async ({ page }, testInfo) => {
  const state = await installApiMocks(page);
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  const trigger = page.getByRole("button", { name: "Delete", exact: true });
  await trigger.click();
  const dialog = page.getByRole("alertdialog", { name: "Delete config?" });
  await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.screenshot({ path: testInfo.outputPath("confirmation-focus.png") });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(trigger).toBeFocused();
  expect(state.requests.filter((request) => request.method === "DELETE")).toHaveLength(0);
});

test("directory dialog contains keyboard focus and restores Browse on cancel", async ({ page }, testInfo) => {
  await installApiMocks(page);
  await page.route("**/api/v1/settings/browse", (route) => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ detail: "No display" }),
  }));
  await page.goto("/");
  const browse = page.getByRole("button", { name: "Browse", exact: true });
  await browse.click();
  const dialog = page.getByRole("dialog", { name: "Select config directory" });
  const input = dialog.getByRole("textbox");
  await expect(input).toBeFocused();
  await input.fill("   ");
  await expect(dialog.getByRole("button", { name: "Use Directory" })).toBeDisabled();
  await page.keyboard.press("Shift+Tab");
  await page.screenshot({ path: testInfo.outputPath("directory-focus.png") });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(input).toBeFocused();
  await input.fill("/data/configs");
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Use Directory" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(input).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(browse).toBeFocused();
});

test("directory validation error keeps input editable and cancellation returns focus", async ({ page }) => {
  await installApiMocks(page);
  await page.route("**/api/v1/settings/browse", (route) => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ detail: "No display" }),
  }));
  await page.route("**/api/v1/settings", (route) => route.fulfill({
    status: route.request().method() === "PUT" ? 400 : 200,
    contentType: "application/json",
    body: JSON.stringify(route.request().method() === "PUT"
      ? { detail: "Directory does not exist" } : { config_dir: "/data/cubos-configs" }),
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Select config directory" });
  await dialog.getByRole("textbox").fill("/missing");
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("alert")).toContainText("Directory does not exist");
  await expect(dialog.getByRole("textbox")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Use Directory" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Browse", exact: true })).toBeFocused();
});
