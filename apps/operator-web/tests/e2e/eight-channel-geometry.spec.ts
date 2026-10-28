import { expect, test } from "@playwright/test";
import { installApiMocks } from "./apiMocks";
import type { GantryConfig } from "../../src/types";

for (const axis of ["x", "y"] as const) {
  test(`eight-channel ${axis} orientation survives editor save and stays visible`, async ({ page }, testInfo) => {
    await installApiMocks(page, { connected: true });
    let config: GantryConfig = {
      serial_port: "/dev/null", gantry_type: "cub_xl",
      cnc: { factory_z_travel_mm: 160, safe_z: 100 },
      working_volume: { x_min: 0, x_max: 600, y_min: 0, y_max: 300, z_min: 0, z_max: 160 },
      instruments: { pipette: { type: "pipette", vendor: "opentrons", pipette_model: "p300_multi_gen2",
        offset_x: 0, offset_y: 0, depth: 0, offline: true,
        channel_geometry: { axis, spacing_mm: 9, length_mm: 80, width_mm: 30, height_mm: 120 } } },
    };
    await page.route("**/api/v1/gantry/cub.yaml", async route => {
      if (route.request().method() === "PUT") config = route.request().postDataJSON();
      await route.fulfill({ json: { filename: "cub.yaml", config } });
    });
    await page.route("**/api/v1/gantry/position", route => route.fulfill({ json: {
      connected: true, calibration_active: false, status: "Idle", x: 410, y: 150, z: 100,
      work_x: 410, work_y: 150, work_z: 100,
    } }));
    await page.goto("/");
    await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
    await expect(page.getByTestId("pipette-channel")).toHaveCount(8);
    await expect(page.getByLabel("Channel orientation")).toHaveValue(axis);
    const head = page.getByTestId("pipette-head");
    const initial = await head.boundingBox();
    expect(initial).not.toBeNull();
    expect(axis === "x" ? initial!.width > initial!.height : initial!.height > initial!.width).toBeTruthy();
    await page.getByLabel("Head length along row (mm)").fill("90");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect.poll(() => config.instruments.pipette.channel_geometry?.length_mm).toBe(90);
    await expect(page.getByText(/pipette · 8 ch · 90 × 30 mm/)).toBeVisible();
    const viewport = await page.getByTestId("deck-visualization").boundingBox();
    const fullHead = await head.boundingBox();
    expect(fullHead!.x).toBeGreaterThanOrEqual(viewport!.x);
    expect(fullHead!.x + fullHead!.width).toBeLessThanOrEqual(viewport!.x + viewport!.width);
    expect(fullHead!.y).toBeGreaterThanOrEqual(viewport!.y);
    expect(fullHead!.y + fullHead!.height).toBeLessThanOrEqual(viewport!.y + viewport!.height);
    expect(await head.evaluate(element => {
      const box = element.getBoundingClientRect();
      const visible = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      return visible !== null && element.closest("svg")!.contains(visible);
    })).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`eight-channel-${axis}.png`), fullPage: true });
  });
}
