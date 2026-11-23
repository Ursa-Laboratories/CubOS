import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
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

async function simulateSingleToolRecovery(page: Page) {
  await installApiMocks(page, { connected: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route("**/api/v1/gantry/cub.yaml", route => route.fulfill({ json: {
    filename: "cub.yaml",
    config: {
      serial_port: "/dev/offline",
      gantry_type: "cub_xl",
      cnc: { factory_z_travel_mm: 80, calibration_block_height_mm: 35, safe_z: 75 },
      working_volume: { x_min: 0, x_max: 300, y_min: 0, y_max: 200, z_min: 0, z_max: 80 },
      grbl_settings: { homing_pull_off: 1 },
      instruments: { pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 0 } },
    },
  } }));
  const token = "server-issued-hover-token";
  const simulation = {
    status: "Idle",
    homes: 0,
    hover: null as { x: number; y: number; z: number } | null,
    backoffs: 0,
    jogWillFault: true,
    verifiedJogs: [] as Array<{ x: number; y: number; z: number; jog_id: string }>,
    jog: undefined as { x: number; y: number; z: number; jog_id: string } | undefined,
    pose: { x: 100, y: 90, z: 30 },
    writes: [] as Array<{ path: string; body: unknown }>,
  };
  const position = () => ({
    status: simulation.status, connected: true, calibration_active: true, ...simulation.pose,
    work_x: simulation.status === "Idle" ? simulation.pose.x : null,
    work_y: simulation.status === "Idle" ? simulation.pose.y : null,
    work_z: simulation.status === "Idle" ? simulation.pose.z : null,
  });
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path.startsWith("/api/v1/gantry/")) {
      simulation.writes.push({ path: path.slice("/api/v1/gantry/".length), body: request.postDataJSON() });
    }
  });
  await page.route("**/api/v1/gantry/position", route => route.fulfill({ json: position() }));
  await page.route("**/api/v1/gantry/calibration/prepare-origin", route => {
    simulation.homes++;
    simulation.status = "Idle";
    simulation.pose = { x: 300, y: 200, z: 80 };
    return route.fulfill({ json: position() });
  });
  await page.route("**/api/v1/gantry/calibration/hover", route => {
    const { jog_ids: jogIds } = route.request().postDataJSON() as { jog_ids?: string[] };
    const verifiedIds = simulation.verifiedJogs.map(({ jog_id }) => jog_id);
    if (!jogIds?.length || JSON.stringify(jogIds) !== JSON.stringify(verifiedIds)) {
      return route.fulfill({ status: 409, json: { detail: "Jog IDs do not match the verified route." } });
    }
    simulation.hover = { ...simulation.pose };
    return route.fulfill({ json: { token, position: position() } });
  });
  await page.route("**/api/v1/gantry/calibration/home-resume", route => {
    simulation.homes++;
    simulation.status = "Idle";
    simulation.pose = { x: 300, y: 200, z: 80 };
    const hoverAvailable = simulation.hover !== null && route.request().postDataJSON()?.token === token;
    return route.fulfill({ json: { position: position(), hover_available: hoverAvailable, blocked_reason: null } });
  });
  await page.route("**/api/v1/gantry/calibration/return-hover", route => {
    const hover = simulation.hover;
    if (!hover) throw new Error("No recorded hover to return to.");
    simulation.pose = hover;
    simulation.hover = null;
    return route.fulfill({ json: { position: position() } });
  });
  await page.route("**/api/v1/gantry/calibration/hover/cancel", route => {
    expect(route.request().postDataJSON()).toEqual({ token });
    simulation.hover = null;
    return route.fulfill({ json: { status: "revoked" } });
  });
  await page.route("**/api/v1/gantry/jog-blocking", route => {
    const jog = route.request().postDataJSON() as NonNullable<typeof simulation.jog>;
    simulation.jog = jog;
    if (!simulation.jogWillFault) {
      const { x, y, z } = simulation.pose;
      simulation.pose = { x: x + jog.x, y: y + jog.y, z: z + jog.z };
      simulation.verifiedJogs.push(jog);
      return route.fulfill({ json: position() });
    }
    simulation.status = "ALARM:1; Pn:Z";
    return route.fulfill({ status: 409, json: { detail: "Gantry entered an alarm state during jog." } });
  });
  await page.route("**/api/v1/gantry/calibration/recovery-context", route => route.fulfill({ json: {
    raw_status: simulation.status === "Home required" ? "<Idle|WPos:100,90,35>" : simulation.status,
    active_limit_axes: simulation.status.startsWith("ALARM") ? ["z"] : [],
    failed_jog_delta: simulation.jog, failed_jog_id: simulation.jog?.jog_id,
    eligible: simulation.status.startsWith("ALARM"),
    pull_off_delta: { x: 0, y: 0, z: 5 }, manual_available: simulation.status.startsWith("ALARM"),
  } }));
  await page.route("**/api/v1/gantry/calibration/recover-limit", route => {
    const jog = simulation.jog;
    expect(jog?.z).toBeLessThan(0);
    expect(jog?.jog_id).toBeTruthy();
    expect(route.request().postDataJSON()).toMatchObject({ z: jog?.z, jog_id: jog?.jog_id });
    simulation.backoffs++;
    simulation.status = "Home required";
    return route.fulfill({ json: {
      status: "recovered", mode: "known_jog", attempts: 1, failed_delta: jog,
      commanded_delta: { x: 0, y: 0, z: 5 }, pull_off: { x: 0, y: 0, z: 5 }, messages: [],
    } });
  });
  await page.route("**/api/v1/gantry/work-coordinates", route => {
    simulation.pose = route.request().postDataJSON();
    return route.fulfill({ json: position() });
  });
  await page.route("**/api/v1/gantry/calibration/restore-soft-limits", route => route.fulfill({ json: position() }));
  return { simulation, token };
}

async function enterSetOrigin(page: Page) {
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await page.getByRole("button", { name: "Calibrate", exact: true }).click();
  await page.getByRole("button", { name: "Full calibration", exact: true }).click();
  const wizard = page.getByRole("dialog", { name: "Gantry calibration" });
  await wizard.getByLabel("Output YAML").fill("recovered-calibration.yaml");
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByRole("button", { name: "Home gantry", exact: true }).click();
  await wizard.getByLabel("Reference height (mm)").fill("32.5");
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByLabel("Tip attached").check();
  await wizard.getByLabel("Measured length (mm)").fill("51.2");
  return wizard;
}

test("a Z limit resumes Set Origin with measurements and no return motion without a checkpoint", async ({ page }, testInfo) => {
  const { simulation } = await simulateSingleToolRecovery(page);
  const wizard = await enterSetOrigin(page);

  await wizard.getByTitle("Z-", { exact: true }).click();
  await expect.poll(() => simulation.backoffs).toBe(1);
  const home = wizard.getByRole("button", { name: "Home and resume", exact: true });
  await expect(home).toBeEnabled();
  await expect(wizard.getByText("Manual recovery", { exact: true })).toHaveCount(0);
  expect(simulation.homes).toBe(1);
  await wizard.screenshot({ path: testInfo.outputPath("z-limit-home-required.png") });

  const beforeHome = simulation.writes.length;
  await home.click();
  await expect(wizard.getByRole("heading", { name: "Set Origin", exact: true })).toBeVisible();
  await expect(wizard.getByLabel("Tip attached")).toBeChecked();
  await expect(wizard.getByLabel("Measured length (mm)")).toHaveValue("51.2");
  await expect(wizard.getByRole("button", { name: "Set origin", exact: true })).toBeEnabled();
  expect(simulation.writes.slice(beforeHome).map(({ path }) => path))
    .toEqual(["calibration/home-resume"]);
  expect(simulation.homes).toBe(2);
  expect(simulation.backoffs).toBe(1);
  await expect(wizard.getByRole("button", { name: "Return above block", exact: true })).toHaveCount(0);

  await wizard.getByRole("button", { name: "Set origin", exact: true }).click();
  await expect(wizard.getByRole("button", { name: "Save", exact: true })).toBeVisible();
  await expect(wizard.getByText(/saved to recovered-calibration\.yaml/)).toBeVisible();
  expect(simulation.writes.find(({ path }) => path === "work-coordinates")?.body)
    .toEqual({ x: 0, y: 0, z: 32.5 });
});

test("recorded hover returns only after Home and renewed clearance confirmation", async ({ page }, testInfo) => {
  const { simulation, token } = await simulateSingleToolRecovery(page);
  const wizard = await enterSetOrigin(page);
  simulation.jogWillFault = false;
  await wizard.getByRole("group", { name: "XY jog step (mm)" }).getByRole("button", { name: "50", exact: true }).click();
  await wizard.getByTitle("X-", { exact: true }).click();
  await expect.poll(() => simulation.pose.x).toBe(250);
  await wizard.getByTitle("Y-", { exact: true }).click();
  await expect.poll(() => simulation.pose.y).toBe(150);
  await wizard.getByRole("group", { name: "Z jog step (mm)" }).getByRole("button", { name: "10", exact: true }).click();
  await wizard.getByTitle("Z-", { exact: true }).click();
  const expectedHover = { x: 250, y: 150, z: 70 };
  await expect.poll(() => simulation.pose).toEqual(expectedHover);
  expect(simulation.verifiedJogs.map(({ x, y, z }) => ({ x, y, z }))).toEqual([
    { x: -50, y: 0, z: 0 },
    { x: 0, y: -50, z: 0 },
    { x: 0, y: 0, z: -10 },
  ]);
  const jogIds = simulation.verifiedJogs.map(({ jog_id }) => jog_id);
  expect(jogIds).toEqual([expect.any(String), expect.any(String), expect.any(String)]);
  expect(jogIds.every(Boolean)).toBe(true);
  expect(new Set(jogIds).size).toBe(3);
  const measurements = { instrument: "pipette", tip_attached: true, tip_length_mm: 51.2, block_height_mm: 32.5 };
  const beforeRecord = simulation.writes.length;
  await wizard.getByText("Recorded block hover", { exact: true }).click();
  const capture = wizard.getByRole("button", { name: "Record block hover", exact: true });
  await expect(capture).toBeDisabled();
  await wizard.getByRole("checkbox", { name: "Same tool, tip, block and fixtures since Home." }).check();
  await expect(capture).toBeDisabled();
  await wizard.getByRole("checkbox", { name: "Current hover and recorded path from Home are clear." }).check();
  expect(simulation.writes).toHaveLength(beforeRecord);
  await capture.click();
  await expect.poll(() => simulation.hover).toEqual(expectedHover);
  expect(simulation.writes.slice(beforeRecord)).toEqual([{
    path: "calibration/hover",
    body: { ...measurements, fixture_confirmed: true, clearance_confirmed: true, path_clear: true, jog_ids: jogIds },
  }]);

  simulation.jogWillFault = true;
  await wizard.getByTitle("Z-", { exact: true }).click();
  await expect.poll(() => simulation.backoffs).toBe(1);
  const home = wizard.getByRole("button", { name: "Home and resume", exact: true });
  await expect(home).toBeEnabled();
  expect(simulation.homes).toBe(1);
  expect(simulation.writes.some(({ path }) => path === "calibration/return-hover")).toBe(false);
  const beforeHome = simulation.writes.length;
  await home.click();
  const returnAboveBlock = wizard.getByRole("button", { name: "Return above block", exact: true });
  await expect(returnAboveBlock).toBeDisabled();
  await expect(wizard.getByLabel("Measured length (mm)")).toHaveValue("51.2");
  expect(simulation.writes.slice(beforeHome)).toEqual([{ path: "calibration/home-resume", body: { token } }]);
  const confirm = wizard.getByRole("checkbox", { name: "Same tool, tip, block and fixtures; recorded path from Home is still clear." });
  await expect(confirm).not.toBeChecked();
  await wizard.screenshot({ path: testInfo.outputPath("return-above-block-confirmation.png") });
  await confirm.check();
  await expect(returnAboveBlock).toBeEnabled();
  expect(simulation.writes.slice(beforeHome)).toHaveLength(1);
  await returnAboveBlock.click();
  await expect.poll(() => simulation.writes.find(({ path }) => path === "calibration/return-hover")).toEqual({
    path: "calibration/return-hover", body: { token, ...measurements, setup_unchanged: true, path_clear: true },
  });
  await expect(wizard.getByRole("heading", { name: "Set Origin", exact: true })).toBeVisible();
  await expect.poll(() => simulation.pose).toEqual(expectedHover);
  await expect(wizard.getByRole("button", { name: "Set origin", exact: true })).toBeEnabled();
  const recoveryActions = simulation.writes.slice(beforeHome).filter(({ path }) => path !== "calibration/hover/cancel");
  expect(recoveryActions.map(({ path }) => path)).toEqual(["calibration/home-resume", "calibration/return-hover"]);
});
