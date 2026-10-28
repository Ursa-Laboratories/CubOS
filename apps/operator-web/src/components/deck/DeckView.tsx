import { Component, lazy, Suspense, useState, type ReactNode } from "react";
import type { DeckResponse, GantryPosition, InstrumentConfig } from "../../types";
import DeckVisualization from "./DeckVisualization";
import "./deck3d.css";

const DeckScene = lazy(() => import("./three/DeckScene"));

export interface DeckViewProps {
  deck: DeckResponse | null;
  instruments: Record<string, InstrumentConfig> | null;
  gantryPosition: GantryPosition | null;
  machineXRange: [number, number];
  machineYRange: [number, number];
  machineZRange: [number, number];
  yAxisMotion: "head" | "bed";
}

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? <div className="deck3d-message" role="status">The 3D view could not load. Switch to 2D to keep viewing the deck.</div>
      : this.props.children;
  }
}

export default function DeckView(props: DeckViewProps) {
  const [mode, setMode] = useState<"2D" | "3D">("2D");
  return (
    <div className="deck-view" onKeyDown={event => event.stopPropagation()}>
      <div className="deck-view-heading">
        <div><h3>Deck Visualization</h3><p>{props.deck?.filename ?? "Load a deck in Workflow to get started"}</p></div>
        <div className="deck-view-toggle" role="group" aria-label="Deck view">
          {(["2D", "3D"] as const).map(value => (
            <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)}>{value}</button>
          ))}
        </div>
      </div>
      {mode === "2D" ? <div className="deck-view-flat"><DeckVisualization {...props} /></div> : (
        <SceneBoundary><Suspense fallback={<div className="deck3d-message" role="status">Loading 3D view…</div>}><DeckScene {...props} /></Suspense></SceneBoundary>
      )}
    </div>
  );
}
