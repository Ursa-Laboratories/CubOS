import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { DeckViewProps } from "../DeckView";
import { buildSceneModel } from "./sceneModel";
import { createSceneRenderer, type SceneRenderer } from "./sceneRenderer";

export default function DeckScene(props: DeckViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null);
  const axis = useRef<SVGSVGElement>(null);
  const scene = useRef<SceneRenderer | null>(null);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [showFrame, setShowFrame] = useState(false);
  const { deck, instruments, gantryPosition, yAxisMotion } = props;
  const [xMin, xMax] = props.machineXRange;
  const [yMin, yMax] = props.machineYRange;
  const [zMin, zMax] = props.machineZRange;
  const model = useMemo(() => buildSceneModel({
    deck, instruments, gantryPosition, yAxisMotion,
    machineXRange: [xMin, xMax], machineYRange: [yMin, yMax], machineZRange: [zMin, zMax],
  }), [deck, instruments, gantryPosition, yAxisMotion, xMin, xMax, yMin, yMax, zMin, zMax]);
  const entries = [...model.objects, ...model.instruments];
  const selected = selectedId === null
    ? model.objects.find(item => item.kind === "well_plate") ?? model.objects[0]
    : entries.find(item => item.id === selectedId);
  const activeId = selected?.id ?? "";
  const canFocus = !!selected && !("positionUnavailable" in selected && selected.positionUnavailable);
  const unavailableCount = model.instruments.filter(instrument => instrument.positionUnavailable).length;

  useEffect(() => {
    if (!host.current || !labels.current || !axis.current) return;
    try {
      const renderer = createSceneRenderer(host.current, labels.current, axis.current, setSelectedId, setError);
      scene.current = renderer;
      return () => { renderer.dispose(); scene.current = null; };
    } catch {
      // WebGL may be disabled, exhausted, or unavailable on a remote desktop.
      queueMicrotask(() => setError("3D graphics are unavailable in this browser. Switch to 2D to view the deck."));
    }
  }, []);
  useEffect(() => { scene.current?.update(model); }, [model]);
  useEffect(() => { scene.current?.select(activeId); }, [activeId]);
  useEffect(() => { scene.current?.labels(showLabels); }, [showLabels]);
  useEffect(() => { scene.current?.frame(showFrame); }, [showFrame]);

  function handleKeys(event: KeyboardEvent<HTMLDivElement>) {
    // The existing gantry widget listens on window. Viewing a deck is never a jog.
    event.stopPropagation();
    if (!(event.target instanceof HTMLCanvasElement)) return;
    const angles: Record<string, [number, number]> = {
      ArrowLeft: [0.15, 0], ArrowRight: [-0.15, 0], ArrowUp: [0, 0.15], ArrowDown: [0, -0.15],
    };
    if (angles[event.key]) {
      event.preventDefault();
      scene.current?.rotate(...angles[event.key]);
    } else if (event.key === "+" || event.key === "=" || event.key === "-") {
      event.preventDefault();
      scene.current?.zoom(event.key === "-" ? 1.15 : 1 / 1.15);
    }
  }

  return (
    // Keyup still reaches the gantry widget so it can release any previously held jog.
    <div className="deck3d" onKeyDownCapture={handleKeys}>
      {error ? <div className="deck3d-message" role="status">{error}</div> : (
        <div className="deck3d-viewport" data-testid="deck-3d">
          <div className="deck3d-canvas" ref={host} />
          <div className="deck3d-labels" ref={labels} />
          <div className="deck3d-toolbar" role="group" aria-label="3D camera">
            <button type="button" title="Return to the angled view" onClick={() => scene.current?.view("orbit")}>◇ Orbit</button>
            <button type="button" onClick={() => scene.current?.view("top")}>▱ Top</button>
            <button type="button" onClick={() => scene.current?.view("fit")}>⛶ Fit</button>
            <button type="button" aria-label="Zoom in" onClick={() => scene.current?.zoom(1 / 1.2)}>+</button>
            <button type="button" aria-label="Zoom out" onClick={() => scene.current?.zoom(1.2)}>−</button>
          </div>
          <div className="deck3d-options">
            <label><input type="checkbox" checked={showLabels} onChange={event => setShowLabels(event.target.checked)} />Labels</label>
            <label title="Show an illustrative gantry frame"><input type="checkbox" checked={showFrame} onChange={event => setShowFrame(event.target.checked)} />Frame</label>
          </div>
          <svg className="deck3d-axis" viewBox="0 0 76 76" ref={axis} aria-label="Deck coordinate axes">
            {(["X", "Y", "Z"] as const).map((name, index) => <g key={name} fill={["#e27574", "#4dbd90", "#64a7ed"][index]} stroke={["#e27574", "#4dbd90", "#64a7ed"][index]}>
              <line data-axis={name} x1="32" y1="43" x2="32" y2="43" strokeWidth="2" />
              <text data-label={name} x="32" y="43" stroke="none" textAnchor="middle">{name}</text>
            </g>)}
          </svg>
          <span className="deck3d-hint">Drag to orbit · Scroll to zoom · Right-drag to pan</span>
          {!model.objects.length && !model.instruments.some(item => item.position) && <div className="deck3d-empty">{deck ? "No positioned labware to display. Add or calibrate labware in Workflow." : "Load a deck in Workflow to see its labware in 3D."}</div>}
        </div>
      )}
      <div className="deck3d-selection">
        <select aria-label="Selected 3D object" value={activeId} onChange={event => setSelectedId(event.target.value)}>
          <option value="">Select labware or an instrument</option>
          {entries.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <button className="deck3d-focus" type="button" disabled={!canFocus || !!error} onClick={() => scene.current?.view("focus")}>Focus selection</button>
      </div>
      <p className="deck3d-caption">
        CAD where matched · Illustrative geometry · Deck coordinates{yAxisMotion === "bed" ? " · Moving-bed gantry" : ""}
        {unavailableCount > 0 ? " · " + unavailableCount + " instrument position" + (unavailableCount === 1 ? "" : "s") + " unavailable" : ""}
        {selected && <><br />{selected.info}</>}
      </p>
    </div>
  );
}
