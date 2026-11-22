import { expect, test, type Page } from "@playwright/test";

const campaign = {
  campaign_id: 42,
  campaign_description: "Synthetic campaign",
  created_at: "2026-01-01T12:00:00Z",
  latest_measurement_at: "2026-01-01T12:05:00Z",
  experiment_count: 1,
  well_count: 1,
  measurement_count: 1,
  measurement_counts: { uvvis: 0, filmetrics: 0, uv_curing: 0, camera: 1, asmi: 0, potentiostat: 0 },
  asmi_measurement_count: 0,
};

async function installResultsMocks(page: Page) {
  const requests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/v1/")) requests.push(`${request.method()} ${path}`);
  });
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const json = (body: unknown, status = 200) => route.fulfill({
      status, contentType: "application/json", body: JSON.stringify(body),
    });
    if (path === "/settings") return json({ config_dir: "/fixture/configs" });
    if (path === "/system/update") return json({ update_available: false });
    if (path === "/gantry/position") {
      return json({ connected: false, status: "Disconnected", x: 0, y: 0, z: 0, calibration_active: false });
    }
    if (path === "/protocol/run-status") return json({ active: false, protocol_file: null });
    if (path.endsWith("/configs") || path === "/protocol/commands" || path === "/gantry/instrument-types" || path === "/fluid-states") return json([]);
    if (["/gantry/instrument-schemas", "/gantry/instrument-methods", "/gantry/instrument-method-params"].includes(path)) return json({});
    return json({ detail: `Unexpected fixture request: ${path}` }, 404);
  });
  return requests;
}

for (const width of [390, 1440]) {
  test(`results distinguish loading, failure and empty data at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const requests = await installResultsMocks(page);
    let result: "error" | "empty" | "populated" = "error";
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/v1/data/campaigns", async (route) => {
      await pending;
      return route.fulfill({
        status: result === "error" ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(result === "error" ? { detail: "Fixture data unavailable" } : result === "empty" ? [] : [campaign]),
      });
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Results", exact: true }).click();
    const panel = page.getByRole("region", { name: "Campaign results output" });
    await expect(panel.getByRole("status")).toHaveText("Loading campaigns...");
    release();
    await expect(panel.getByRole("alert")).toHaveText("Data load failed: Fixture data unavailable");
    await expect(panel.getByText(/No campaigns yet/)).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`results-error-${width}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);

    result = "empty";
    const refresh = panel.getByRole("button", { name: "Refresh" });
    await refresh.focus();
    await page.keyboard.press("Enter");
    await expect(panel.getByRole("status")).toContainText("No campaigns yet");
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(refresh).toBeFocused();

    result = "populated";
    await page.keyboard.press("Enter");
    await expect(panel.getByText("Campaign #42")).toBeVisible();
    result = "error";
    await page.keyboard.press("Enter");
    await expect(panel.getByRole("alert")).toContainText("Fixture data unavailable");
    await expect(panel.getByText("Campaign #42")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Download Data" })).toBeEnabled();
    expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
  });
}

test("failed downloads announce the error and allow keyboard retry", async ({ page }) => {
  const requests = await installResultsMocks(page);
  await page.route("**/api/v1/data/campaigns", (route) => route.fulfill({ json: [campaign] }));
  let attempts = 0;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/data/campaigns/42/data.zip", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({ status: 503, json: { detail: "Fixture export unavailable" } });
    }
    await pending;
    return route.fulfill({
      contentType: "application/zip",
      body: Buffer.from("504b0506000000000000000000000000000000000000", "hex"),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Results", exact: true }).click();
  const panel = page.getByRole("region", { name: "Campaign results output" });
  const download = panel.getByRole("button", { name: "Download Data" });
  await download.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("alert")).toHaveText("Export failed: Fixture export unavailable");
  await expect(download).toBeEnabled();
  await download.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("button", { name: "Preparing..." })).toBeDisabled();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  const downloaded = page.waitForEvent("download");
  release();
  expect((await downloaded).suggestedFilename()).toBe("campaign_42_data.zip");
  await expect(download).toBeEnabled();
  expect(attempts).toBe(2);
  expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
});
