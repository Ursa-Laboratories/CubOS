import { test, expect } from "@playwright/test";
import { installApiMocks } from "./apiMocks";

test("Set Origin measures a seated tip and selecting a step does not jog", async ({ page }, testInfo) => {
  const state = await installApiMocks(page, { connected: true });
  await page.route("**/api/v1/gantry/cub.yaml", route => route.fulfill({ json: {
    filename: "cub.yaml", config: {
      gantry_type: "genmitsu_4040_pro_max", serial_port: "/dev/mock",
      cnc: { factory_z_travel_mm: 80, calibration_block_height_mm: 35 },
      working_volume: { x_min: 0, x_max: 400, y_min: 0, y_max: 400, z_min: 0, z_max: 80 },
      instruments: { pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 0 } },
    },
  } }));
  await page.route("**/api/v1/gantry/calibration/prepare-origin", route => route.fulfill({ json: {
    status: "Idle", connected: true, x: 400, y: 400, z: 80, work_x: 400, work_y: 400, work_z: 80,
  } }));
  await page.goto("/");
  await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
  await page.getByRole("button", { name: "Calibrate", exact: true }).click();
  await page.getByRole("button", { name: "Full calibration", exact: true }).click();
  const wizard = page.getByRole("dialog", { name: "Gantry calibration" });
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByRole("button", { name: "Home gantry" }).click();
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();

  await expect(wizard.getByRole("checkbox", { name: /tip attached/i })).toBeChecked();
  const guide = wizard.getByRole("img", { name: /black nozzle/ });
  const capture = wizard.getByRole("button", { name: "Set origin", exact: true });
  await expect(guide).toBeVisible();
  await expect(capture).toBeDisabled();
  await wizard.getByRole("textbox", { name: "Measured length (mm)" }).fill("42");
  await expect(capture).toBeEnabled();

  const xy = wizard.getByRole("group", { name: "XY jog step (mm)" });
  const z = wizard.getByRole("group", { name: "Z jog step (mm)" });
  await xy.getByRole("button", { name: "100", exact: true }).click();
  await z.getByRole("button", { name: "50", exact: true }).click();
  await expect(z.getByRole("button", { name: "100", exact: true })).toHaveCount(0);
  await expect(xy.getByRole("button", { name: "100", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(z.getByRole("button", { name: "50", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(state.requests.filter(r => r.method === "POST" && r.path.includes("/jog"))).toHaveLength(0);
  await page.screenshot({ path: testInfo.outputPath("set-origin.png") });
});
