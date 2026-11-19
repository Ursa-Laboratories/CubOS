# Operator instrument preview

From `apps/operator-web`, build Operator and serve it with Python 3.9 or newer.

```sh
npm ci
npm run build
python3 examples/instrument-preview/serve.py
```

Open [Deck Visualization](http://127.0.0.1:5197/) and choose a configuration in **Preview setup**. Each example has a direct link.

- [Pipettes](http://127.0.0.1:5197/?setup=pipettes)
- [Multichannel and 300 µL pipettes](http://127.0.0.1:5197/?setup=multichannel)
- [Mechanical tools](http://127.0.0.1:5197/?setup=mechanics)
- [Capper variants](http://127.0.0.1:5197/?setup=cappers)
- [Optics and UV curing](http://127.0.0.1:5197/?setup=optics)
- [Imaging and illumination](http://127.0.0.1:5197/?setup=imaging)
- [Camera and light variants](http://127.0.0.1:5197/?setup=camera-mounts)
- [Electrochemistry](http://127.0.0.1:5197/?setup=electrochemistry)
- [Raman probe](http://127.0.0.1:5197/?setup=raman)

The local server supplies illustrative gantry and deck configurations to the built Operator. It binds to localhost, rejects write requests, and has no connection to a CubOS station. The offsets give each head space in the viewer. Use a calibrated gantry configuration for hardware operation.

With the server running, check the examples in Chromium from `apps/operator-web`.

```sh
npx playwright install chromium
node examples/instrument-preview/check.mjs
```

Pass an output directory as the first argument to capture the full Operator view and a **Tools** close-up for every setup. Pass a different preview URL as the second argument when using a custom port.
