# Preview the 3D deck without hardware

From `apps/operator-web`, run:

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5187 --strictPort
```

Open <http://127.0.0.1:5187/tests/deck-3d-preview.html>.
In Workflow, open `sample-gantry.yaml` on the Gantry tab, then
`sample-deck.yaml` on the Deck tab. Choose Visualize and 3D.

The blue banner identifies sample data. **Simulated instrument pose** supplies
a fixed pose; **Empty deck** checks the empty state. Every API request is
answered by the fixture. Gantry mutation requests are blocked and counted in
the banner. No backend, serial connection, or physical hardware is used.

Use **Setup** in the blue banner to switch layouts without reloading:

| Layout | Deck size | Sample contents |
|---|---|---|
| CAD labware | 600 × 400 mm | Imported Cubware plate holder and native-size 30-tip holder, open wells and hollow vials |
| Compact | 300 × 230 mm | Original plate, rack, holder, and disposal |
| Mixed labware | 600 × 400 mm | 6-, 24-, 96-, and 384-well plates, a raised holder, vial grid, tall vials, tips, disposal |
| Large deck | 900 × 600 mm | More plates, two tip racks, two vial grids, a rotated plate, and two instrument silhouettes |
| Dense deck | 1200 × 800 mm | 24 plates and 6 tip racks, totaling 6,336 displayed well/tip positions |

The larger dimensions are illustrative layouts for visual testing, not machine
travel specifications. **Fit** restores the whole deck; choose a plate and
**Focus selection** to inspect its wells. The vial selector includes grid names
so matching vial IDs on different grids remain distinguishable.

The default **CAD labware** scenario loads two actual GLBs from the public
asset registry. The plate holder is shown empty: its seat registration is not
yet mapped, so a holder containing a plate keeps the illustrative fallback.
The tip holder uses an explicit visual-only model identifier
and its mesh dimensions (138 × 21 × 66 mm); its older physical YAML describes
different axes/dimensions, so it is not automatically mapped to that config.
The native-size and identity gates prevent stretching an unrelated CAD mesh.
An asset load failure retains the procedural shape. API calls remain mocked;
the page permits ordinary same-origin requests for its static model files.

Check orbit, top, fit, zoom, pan, selection, focus, Labels, Frame, light/dark
theme, and switching between 2D and 3D. With the canvas focused, arrow keys
rotate the camera without increasing the hardware command counter. Released
keys still reach the existing jog handler so a previously held jog can stop.

The fixture is a development page; it is not an entry point in the production
build. `npm test -- src/components/deck` runs the automated geometry and UI
checks. Real WebGL rendering is checked manually with this page.
