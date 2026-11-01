import { expect, test } from "@playwright/test";
import { parse } from "yaml";
import { installApiMocks } from "./apiMocks";
import type { ProtocolConfig, ProtocolStep } from "../../src/types";

test("edits paired dispense rows, saves arrays, and reloads them in the Operator", async ({ page }) => {
  const state = await installApiMocks(page);
  let steps: ProtocolStep[] = [{ command: "multi_dispense", args: {
    source: "plate_1.A1", destinations: ["plate_1.B1", "plate_1.C1"], volumes: [20, 30],
  } }];
  let saved: ProtocolConfig | undefined;
  await page.route("**/api/v1/protocol/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(payload) });
    if (path.endsWith("/commands")) return json([{ name: "multi_dispense", description: "Aspirate once, dispense portions", args: [
      { name: "source", type: "str", required: true, default: null },
      { name: "destinations", type: "list[str]", required: true, default: null },
      { name: "volumes", type: "list[float]", required: true, default: null },
    ] }]);
    if (path.endsWith("/configs")) return json(["multi_dispense.yaml"]);
    if (path.endsWith("/multi_dispense.yaml")) {
      if (route.request().method() === "PUT") {
        saved = route.request().postDataJSON() as ProtocolConfig;
        steps = saved.protocol;
      }
      return json({ filename: "multi_dispense.yaml", steps, positions: null });
    }
    return route.fallback();
  });
  const openProtocol = async () => {
    await page.getByLabel("Gantry config", { exact: true }).selectOption("cub.yaml");
    await page.getByRole("button", { name: "Deck", exact: true }).click();
    await page.getByLabel("Deck config", { exact: true }).selectOption("asmi_deck.yaml");
    await page.getByRole("button", { name: "Protocol", exact: true }).click();
    await page.getByLabel("Protocol config", { exact: true }).selectOption("multi_dispense.yaml");
  };
  await page.goto("/");
  await openProtocol();
  await expect(page.getByRole("table", { name: "Step 1 dispense destinations" })).toBeVisible();
  await page.getByRole("button", { name: "Add destination", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByLabel("Step 1 destination 3", { exact: true }).fill("plate_1.D1");
  await page.getByLabel("Step 1 volume 3 (µL)", { exact: true }).fill("50.5");
  await page.getByRole("button", { name: "Remove destination 2 from step 1", exact: true }).click();
  await expect(page.getByLabel("Step 1 volume 2 (µL)", { exact: true })).toHaveValue("50.5");
  await page.getByLabel("Step 1 volume 1 (µL)", { exact: true }).fill("20oops");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByLabel("Step 1 volume 1 (µL)", { exact: true }).fill("20");
  await page.getByRole("button", { name: "Edit raw YAML", exact: true }).click();
  const yaml = parse(await page.getByLabel("Raw YAML", { exact: true }).inputValue());
  expect(yaml.protocol[0].multi_dispense).toEqual({ source: "plate_1.A1", destinations: ["plate_1.B1", "plate_1.D1"], volumes: [20, 50.5] });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => saved?.protocol[0].args).toEqual(yaml.protocol[0].multi_dispense);
  await page.reload();
  await expect(page.getByLabel("Step 1 destination 2", { exact: true })).toHaveValue("plate_1.D1");
  await expect(page.getByLabel("Step 1 volume 2 (µL)", { exact: true })).toHaveValue("50.5");
  expect(state.requests.filter(r => r.path === "/runs" || r.path === "/gantry/connect")).toEqual([]);
});
