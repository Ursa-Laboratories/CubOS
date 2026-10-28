// Manual browser fixture. All API calls terminate here; this page cannot operate hardware.
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../src/App";
import { previewScenarios } from "./deck-3d-scenarios";
import "../src/index.css";

let scenario = previewScenarios[0];
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
  if (path === "/gantry/position") return json({ ...scenario.pose, work_x: scenario.pose.x, work_y: scenario.pose.y, work_z: scenario.pose.z, connected, status: "Idle", calibration_active: false });
  if (path === "/gantry/instrument-types") return json([{ type: "pipette", vendors: ["sartorius"] }]);
  if (path === "/gantry/pipette-models") return json([]);
  if (path.startsWith("/gantry/instrument-")) return json({});
  if (path === "/gantry/sample-gantry.yaml") return json({ filename: "sample-gantry.yaml", config: scenario.gantry });
  if (path === "/deck/sample-deck.yaml" || path === "/deck/cub_deck.yaml") return json({ ...scenario.deck, filename: path.split("/").pop(), labware: empty ? [] : scenario.deck.labware });
  if (path === "/deck/preview-wells") {
    const config = JSON.parse(String(init?.body ?? "{}")) as { name?: string };
    const item = scenario.deck.labware.find(entry => entry.config.name === config.name);
    return json(item?.wells ?? item?.positions ?? {});
  }
  if (path === "/data/campaigns" || path === "/fluid-states") return json([]);
  if (path.includes("update")) return json({ current_sha: "offline-preview", latest_sha: "offline-preview", commits_behind: 0, update_available: false, summary: [], error: null });
  return json({ detail: "Not available in preview: " + method + " " + path }, 404);
};
document.documentElement.dataset.theme = "light";
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
export default function Preview() {
  const [setupId, setSetupId] = useState(scenario.id);
  const [pose, setPose] = useState(false);
  const [emptyDeck, setEmptyDeck] = useState(false);
  const [attempts, setAttempts] = useState(0);
  useEffect(() => {
    const handler = () => setAttempts(hardwareRequests);
    window.addEventListener("preview-status", handler);
    return () => window.removeEventListener("preview-status", handler);
  }, []);
  return <>
    <div style={{ position: "sticky", top: 0, zIndex: 100, padding: "6px 16px", background: "#233c78", color: "#fff", fontSize: 12, display: "flex", flexWrap: "wrap", gap: "6px 16px", alignItems: "center" }}>
      <strong>OFFLINE PREVIEW</strong>
      <label style={{ display: "flex", gap: 6, alignItems: "center" }}>Setup
        <select aria-label="Preview setup" value={setupId} style={{ font: "inherit", padding: "4px 8px", background: "#fff", color: "#172137", border: "1px solid #ccd7ed", borderRadius: 4 }} onChange={event => {
          scenario = previewScenarios.find(item => item.id === event.target.value) ?? previewScenarios[0];
          setSetupId(scenario.id);
          empty = false; setEmptyDeck(false);
          void queryClient.invalidateQueries();
        }}>{previewScenarios.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
      </label>
      <span title={scenario.description}>Illustrative sample layouts</span>
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
