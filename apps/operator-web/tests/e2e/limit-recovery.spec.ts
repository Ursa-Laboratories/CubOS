import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

test("manual Y recovery requires direction and clearance and keeps Stop available", async ({ page }, testInfo) => {
  await installApiMocks(page, { connected: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const position = { connected: true, calibration_active: false, status: "ALARM:3; Pn:Y", x: 0, y: 0, z: 0, work_x: null, work_y: null, work_z: null };
  await page.route("**/api/v1/gantry/position", (route) => route.fulfill({ json: position }));
  await page.route("**/api/v1/gantry/calibration/recovery-context", (route) => route.fulfill({ json: {
    raw_status: position.status, active_limit_axes: ["y"], failed_jog_delta: null,
    eligible: false, blocked_reason: "Original jog unknown.", pull_off_delta: null, manual_available: true,
  } }));
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  const commands: Array<{ path: string; body: unknown }> = [];
  await page.route("**/api/v1/gantry/calibration/recover-limit/manual", async (route) => {
    commands.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
    await pending;
    await route.fulfill({ status: 409, json: { detail: "Recovery cancelled." } });
  });
  await page.route("**/api/v1/gantry/jog-cancel", async (route) => {
    commands.push({ path: new URL(route.request().url()).pathname, body: null });
    await route.fulfill({ json: position });
  });
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await page.getByText("Manual recovery", { exact: true }).click();
  await expect(page.getByLabel("Away direction")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Move Y 1 mm" })).toBeDisabled();
  await expect(page.getByRole("checkbox")).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("manual-y-recovery-confirmation.png") });
  expect(commands).toHaveLength(0);
  await page.getByLabel("Away direction").selectOption("1");
  await expect(page.getByRole("button", { name: "Move Y+ 1 mm" })).toBeDisabled();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Move Y+ 1 mm" }).click();
  await expect(page.getByRole("button", { name: "Stop recovery" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Home", exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("manual-y-recovery-stop.png") });
  await page.getByRole("button", { name: "Stop recovery" }).click();
  finish();
  await expect(page.getByText("Recovery cancelled.", { exact: true })).toBeVisible();
  expect(commands).toEqual([
    { path: "/api/v1/gantry/calibration/recover-limit/manual", body: { axis: "y", away_direction: 1, operator_confirmed: true } },
    { path: "/api/v1/gantry/jog-cancel", body: null },
  ]);
});
