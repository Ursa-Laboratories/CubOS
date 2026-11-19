import { Component, lazy, Suspense } from "react";
import type { ComponentProps, ReactNode } from "react";
import { panelTitle } from "../../theme";
import type { Coordinate3D, GantryConfig, GantryPosition } from "../../types";
import DeckVisualization from "./DeckVisualization";
import "./DeckVisualizationCard.css";

const PolarDeckScene = lazy(() => import("./PolarDeckScene"));
const JOG_KEYS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "x", "X", "z", "Z"]);

export type DeckViewMode = "2D" | "3D";

interface Props extends ComponentProps<typeof DeckVisualization> {
  mode: DeckViewMode;
  onModeChange: (mode: DeckViewMode) => void;
  positionQuerySucceeded: boolean;
  machineZRange?: [number, number];
  originPolicy?: GantryConfig["origin_policy"];
  gantryType?: GantryConfig["gantry_type"];
}

function liveWorkPosition(position: GantryPosition | null): Coordinate3D | null {
  if (!position?.connected || position.calibration_active) return null;
  const { work_x: x, work_y: y, work_z: z } = position;
  if (x === null || y === null || z === null) return null;
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) ? { x, y, z } : null;
}

class DeckSceneBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export default function DeckVisualizationCard({
  mode,
  onModeChange,
  positionQuerySucceeded,
  machineZRange,
  originPolicy,
  gantryType,
  ...deckProps
}: Props) {
  return (
    <div
      className="deck-visualization-card"
      onKeyDown={(event) => {
        // Key releases still reach Gantry Control to stop any held jog.
        if (mode === "3D" && JOG_KEYS.has(event.key)) event.stopPropagation();
      }}
    >
      <div className="deck-visualization-card__header">
        <h3 style={{ ...panelTitle, margin: 0 }}>Deck Visualization</h3>
        <div className="deck-visualization-card__toggle" role="group" aria-label="Deck view">
          {(["2D", "3D"] as const).map((view) => (
            <button key={view} type="button" aria-pressed={mode === view} onClick={() => onModeChange(view)}>
              {view}
            </button>
          ))}
        </div>
      </div>
      <div className="deck-visualization-card__viewport">
        {mode === "2D" ? (
          <DeckVisualization {...deckProps} />
        ) : (
          <DeckSceneBoundary fallback={(
            <div className="deck-visualization-card__fallback">
              <div role="status">3D unavailable. Showing the 2D view.</div>
              <div><DeckVisualization {...deckProps} /></div>
            </div>
          )}>
            <Suspense fallback={<div className="deck-visualization-card__loading" role="status">Loading 3D view…</div>}>
              <PolarDeckScene
                {...deckProps}
                gantryPosition={positionQuerySucceeded ? liveWorkPosition(deckProps.gantryPosition) : null}
                machineZRange={machineZRange}
                originPolicy={originPolicy}
                gantryType={gantryType}
                onShow2D={() => onModeChange("2D")}
              />
            </Suspense>
          </DeckSceneBoundary>
        )}
      </div>
    </div>
  );
}
