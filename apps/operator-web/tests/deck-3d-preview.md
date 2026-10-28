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

Check orbit, top, fit, zoom, pan, selection, focus, Labels, Frame, light/dark
theme, and switching between 2D and 3D. With the canvas focused, arrow keys
rotate the camera without increasing the hardware command counter. Released
keys still reach the existing jog handler so a previously held jog can stop.

The fixture is a development page; it is not an entry point in the production
build. `npm test -- src/components/deck` runs the automated geometry and UI
checks. Real WebGL rendering is checked manually with this page.
