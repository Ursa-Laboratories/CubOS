import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

test("verified calibration Home clears stale polls and a later Y fault stays blocked", async ({ page }, testInfo) => {
  await installApiMocks(page, { connected: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  let status = "Idle";
  let homeStarted = false;
  let delayedPoll = false;
  let pollReleased = false;
  let freshReads = 0;
  let releaseHome!: () => void;
  let releasePoll!: () => void;
  const homeGate = new Promise<void>((resolve) => { releaseHome = resolve; });
  const pollGate = new Promise<void>((resolve) => { releasePoll = resolve; });
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/gantry/")) posts.push(new URL(request.url()).pathname);
  });
  const position = (state: string) => ({
    connected: true, calibration_active: homeStarted, status: state, x: 0, y: 0, z: 80,
    work_x: state === "Idle" ? 0 : null, work_y: state === "Idle" ? 0 : null, work_z: state === "Idle" ? 80 : null,
  });
  await page.route("**/api/v1/gantry/position", async (route) => {
    if (homeStarted && !delayedPoll) {
      delayedPoll = true;
      await pollGate;
      pollReleased = true;
      await route.fulfill({ json: position("Home required") });
      return;
    }
    if (pollReleased) freshReads += 1;
    await route.fulfill({ json: position(status) });
  });
  await page.route("**/api/v1/gantry/calibration/prepare-origin", async (route) => {
    homeStarted = true;
    status = "Homing";
    await homeGate;
    status = "Idle";
    await route.fulfill({ json: position(status) });
  });
  await page.route("**/api/v1/gantry/calibration/recovery-context", (route) => route.fulfill({ json: {
    raw_status: status, active_limit_axes: ["y"], failed_jog_delta: null, eligible: false,
    blocked_reason: "Original jog unknown.", pull_off_delta: null, manual_available: true,
  } }));
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await page.getByRole("button", { name: "Calibrate", exact: true }).click();
  await page.getByRole("button", { name: "Full calibration", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Gantry calibration" });
  await dialog.getByRole("button", { name: "Continue", exact: true }).click();
  await dialog.getByRole("button", { name: "Home gantry", exact: true }).click();
  await expect.poll(() => delayedPoll).toBe(true);
  releaseHome();
  await expect(dialog.getByText("Homed.", { exact: true })).toBeVisible();
  releasePoll();
  await expect.poll(() => freshReads).toBeGreaterThan(0);
  await expect(dialog.getByText("GANTRY ALARM", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("reference-height-homed.png") });

  status = "ALARM:3; Pn:Y";
  await expect(dialog.getByText("GANTRY ALARM", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  await expect(dialog.getByText("Homed.", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("reference-height-y-alarm.png") });
  expect(posts).toEqual(["/api/v1/gantry/calibration/prepare-origin"]);
});
