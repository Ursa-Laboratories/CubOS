// Manual browser fixture. All API calls terminate here; this page cannot operate hardware.
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";
import type { DeckResponse, GantryConfig, WellPosition } from "../src/types";
import "../src/index.css";

const grid = (x: number, y: number, z: number, rows: number, columns: number, pitch = 9): Record<string, WellPosition> =>
  Object.fromEntries(Array.from({ length: rows * columns }, (_, i) => {
    const row = Math.floor(i / columns), col = i % columns;
    return [String.fromCharCode(65 + row) + (col + 1), { x: x + col * pitch, y: y - row * pitch, z }];
  }));
const wells = grid(25, 95, 14.35, 8, 12);
const tips = grid(175, 205, 55, 8, 12);
const vials = grid(35, 200, 48, 3, 4, 24);
const plateConfig = {
  type: "well_plate" as const, name: "96-well plate", model_name: "sample_96",
  rows: 8, columns: 12, length: 127.76, width: 85.47, height: 14.35,
  x_offset: 9, y_offset: 9, calibration: { a1: wells.A1, a2: wells.A2 },
};
const sampleDeck: DeckResponse = {
  filename: "sample-deck.yaml",
  labware: [
    { key: "plate", config: plateConfig, wells, geometry: { length: 127.76, width: 85.47, height: 14.35 }, positions: wells },
    { key: "tips", config: { type: "tip_rack", name: "Tips", model_name: "sample_tips", rows: 8, columns: 12 }, wells: null, positions: tips, geometry: { length: 127, width: 85, height: 55 } },
    { key: "vials", config: { type: "vial_holder", name: "Vials", labware_seat_height_from_bottom: 13, location: { x: 20, y: 140, z: 0 }, vials: Object.fromEntries(Object.entries(vials).map(([id, p]) => [id, { model_name: "sample_vial", location: p, height: 35, diameter: 15, capacity_ul: 2000, working_volume_ul: 1500 }])) }, wells: null, location: { x: 20, y: 140, z: 0 }, positions: vials, geometry: { length: 110, width: 85, height: 20 } },
    { key: "waste", config: { type: "tip_disposal", name: "Tip disposal", location: { x: 220, y: 65, z: 35 } }, wells: null, location: { x: 220, y: 65, z: 35 }, geometry: { length: 85, width: 62, height: 35 } },
  ],
};
const gantry: GantryConfig = {
  serial_port: "OFFLINE-PREVIEW", gantry_type: "cub", cnc: { factory_z_travel_mm: 150, y_axis_motion: "bed" },
  working_volume: { x_min: 0, x_max: 300, y_min: 0, y_max: 230, z_min: 0, z_max: 150 },
  instruments: { pipette: { type: "pipette", vendor: "sartorius", offset_x: 0, offset_y: 0, depth: 20 } },
};
let connected = false, empty = false, hardwareRequests = 0;
const requests: { method: string; path: string }[] = [];
window.fetch = async (input, init) => {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const path = new URL(raw, location.origin).pathname.replace(/^\/api\/v1/, "");
  const method = init?.method ?? "GET";
  requests.push({ method, path });
  const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  if (method !== "GET" && path.startsWith("/gantry/")) {
    hardwareRequests += 1;
    window.dispatchEvent(new Event("preview-status"));
    return json({ detail: "Hardware commands are disabled in this offline preview." }, 405);
  }
  if (path === "/settings") return json({ config_dir: "OFFLINE UI PREVIEW / sample data" });
  if (path === "/deck/configs") return json(["sample-deck.yaml"]);
  if (path === "/gantry/configs") return json(["sample-gantry.yaml"]);
  if (path === "/protocol/configs" || path === "/protocol/commands") return json([]);
  if (path === "/protocol/run-status") return json({ active: false });
  if (path === "/gantry/position") return json({ x: 100, y: 120, z: 100, work_x: 100, work_y: 120, work_z: 100, connected, status: "Idle", calibration_active: false });
  if (path === "/gantry/instrument-types") return json([{ type: "pipette", vendors: ["sartorius"] }]);
  if (path === "/gantry/pipette-models") return json([]);
  if (path.startsWith("/gantry/instrument-")) return json({});
  if (path === "/gantry/sample-gantry.yaml") return json({ filename: "sample-gantry.yaml", config: gantry });
  if (path === "/deck/sample-deck.yaml" || path === "/deck/cub_deck.yaml") return json({ ...sampleDeck, filename: path.split("/").pop(), labware: empty ? [] : sampleDeck.labware });
  if (path === "/deck/preview-wells") return json(wells);
  if (path === "/data/campaigns" || path === "/fluid-states") return json([]);
  if (path.includes("update")) return json({ current_sha: "offline-preview", latest_sha: "offline-preview", commits_behind: 0, update_available: false, summary: [], error: null });
  return json({ detail: "Not available in preview: " + method + " " + path }, 404);
};
document.documentElement.dataset.theme = "light";
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
export default function Preview() {
  const [pose, setPose] = useState(false);
  const [emptyDeck, setEmptyDeck] = useState(false);
  const [attempts, setAttempts] = useState(0);
  useEffect(() => {
    const handler = () => setAttempts(hardwareRequests);
    window.addEventListener("preview-status", handler);
    return () => window.removeEventListener("preview-status", handler);
  }, []);
  return <>
    <div style={{ position: "sticky", top: 0, zIndex: 100, padding: "6px 16px", background: "#233c78", color: "#fff", fontSize: 12, display: "flex", gap: 18, alignItems: "center" }}>
      <strong>OFFLINE UI PREVIEW · Sample data</strong>
      <label><input type="checkbox" checked={pose} onChange={event => { connected = event.target.checked; setPose(connected); void queryClient.invalidateQueries(); }} /> Simulated instrument pose</label>
      <label><input type="checkbox" checked={emptyDeck} onChange={event => { empty = event.target.checked; setEmptyDeck(empty); void queryClient.invalidateQueries(); }} /> Empty deck</label>
      <span>Hardware commands attempted: {attempts}</span>
    </div>
    <App />
  </>;
}
const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><QueryClientProvider client={queryClient}><Preview /></QueryClientProvider></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
