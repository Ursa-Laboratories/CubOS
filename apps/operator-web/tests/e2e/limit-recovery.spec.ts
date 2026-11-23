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

test("a Z limit backs off once and Home resumes Set Origin without another move", async ({ page }, testInfo) => {
  await installApiMocks(page, { connected: true });
  let status = "Idle";
  let homes = 0;
  let backoffs = 0;
  let finishBackoff!: () => void;
  const backoffGate = new Promise<void>(resolve => { finishBackoff = resolve; });
  const writes: string[] = [];
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path.startsWith("/api/v1/gantry/")) writes.push(path);
  });
  let jog: { x: number; y: number; z: number; jog_id: string } | undefined;
  const position = () => ({
    status, connected: true, calibration_active: true, x: 100, y: 90, z: 30,
    work_x: status === "Idle" ? 100 : null, work_y: status === "Idle" ? 90 : null,
    work_z: status === "Idle" ? 30 : null,
  });
  await page.route("**/api/v1/gantry/position", route => route.fulfill({ json: position() }));
  await page.route("**/api/v1/gantry/calibration/prepare-origin", route => {
    homes++;
    status = "Idle";
    return route.fulfill({ json: position() });
  });
  await page.route("**/api/v1/gantry/jog-blocking", route => {
    jog = route.request().postDataJSON();
    status = "ALARM:1; Pn:Z";
    return route.fulfill({ status: 409, json: { detail: "Gantry entered an alarm state during jog." } });
  });
  await page.route("**/api/v1/gantry/calibration/recovery-context", route => route.fulfill({ json: {
    raw_status: status === "Home required" ? "<Idle|WPos:100,90,35>" : status,
    active_limit_axes: status === "Home required" ? [] : ["z"],
    failed_jog_delta: jog, failed_jog_id: jog?.jog_id, eligible: status.startsWith("ALARM"),
    pull_off_delta: { x: 0, y: 0, z: 5 }, manual_available: status.startsWith("ALARM"),
  } }));
  await page.route("**/api/v1/gantry/calibration/recover-limit", async route => {
    expect(jog?.z).toBeLessThan(0);
    expect(jog?.jog_id).toBeTruthy();
    expect(route.request().postDataJSON()).toMatchObject({ z: jog?.z, jog_id: jog?.jog_id });
    backoffs++;
    await backoffGate;
    status = "Home required";
    return route.fulfill({ json: {
      status: "recovered", mode: "known_jog", attempts: 1, failed_delta: jog,
      commanded_delta: { x: 0, y: 0, z: 5 }, pull_off: { x: 0, y: 0, z: 5 }, messages: [],
    } });
  });

  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await page.getByRole("button", { name: "Calibrate", exact: true }).click();
  await page.getByRole("button", { name: "Full calibration", exact: true }).click();
  const wizard = page.getByRole("dialog", { name: "Gantry calibration" });
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByRole("button", { name: "Home gantry", exact: true }).click();
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByTitle("Z-", { exact: true }).click();
  await expect.poll(() => backoffs).toBe(1);
  await expect(wizard.getByRole("status").filter({ hasText: /recovering/i })).toBeVisible();
  await expect(wizard.getByRole("button", { name: "Stop recovery" })).toHaveCount(0);
  finishBackoff();
  const home = wizard.getByRole("button", { name: "Home and resume", exact: true });
  await expect(home).toBeEnabled();
  await expect(wizard.getByText("Manual recovery", { exact: true })).toHaveCount(0);
  expect(homes).toBe(1);
  await page.screenshot({ path: testInfo.outputPath("z-limit-home-required.png") });
  const beforeHome = writes.length;
  await home.click();
  await expect(wizard.getByText("Homed.", { exact: true })).toBeVisible();
  await expect(wizard.getByRole("heading", { name: "Set Origin", exact: true })).toBeVisible();
  expect(writes.slice(beforeHome)).toEqual(["/api/v1/gantry/calibration/prepare-origin"]);
  expect(homes).toBe(2);
  expect(backoffs).toBe(1);
});
