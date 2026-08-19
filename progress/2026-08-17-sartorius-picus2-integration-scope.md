# Sartorius Picus 2 — CubOS integration feature scope

Research date: 2026-08-17. Target: a `pipette/sartorius` vendor implementing
the existing `PipetteInstrument` interface to the same completeness as
`pipette/opentrons`.

---

## 1. Verdict

**The Picus 2 is a better fit for the CubOS pipette interface than the
Opentrons pipette it would sit beside.** Every abstract method on
`PipetteInstrument` can be implemented, and three of them (`blowout`,
`drop_tip`, `health_check`) map to real vendor capabilities that the
Opentrons driver only fakes with plunger-position moves.

The mismatch is not in the *methods* — it is in the *state model*. CubOS's
pipette types are built around a stepper pushing a plunger a known number of
millimetres (`PipetteConfig.mm_to_ul`, `prime_position`,
`PipetteStatus.position_mm`). The Picus 2 is volume-native: you command
microlitres, it owns its own piston, and it reports no position at all. Four
interface obligations therefore become driver-side bookkeeping rather than
hardware readback (§5, flags **F-2** / **F-5** / **F-6**).

Nothing on the interface is *impossible*. One thing is genuinely
unsupported (`prime()` has no analogue), several are degraded (quantized
volume and speed, emulated `mix`), and the largest risks are operational,
not architectural: arming remote motor control appears to need a device-side
confirmation (**F-1**), and the pipette runs on a battery (**F-10**).

Estimated effort: **~3–4 days of implementation + test work**, plus hardware
bring-up. No changes needed to the protocol engine, the API, the Operator UI,
or the validation layer.

---

## 2. What we already have

### 2.1 The CubOS side

| Piece | Location | Status |
|---|---|---|
| Generic interface | [interface.py](packages/core/src/cubos/instruments/pipette/interface.py) | 12 abstract members, unchanged |
| Shared models | [models.py](packages/core/src/cubos/instruments/pipette/models.py) | needs a small refactor (**F-2**) |
| Reference driver | [vendors/opentrons.py](packages/core/src/cubos/instruments/pipette/vendors/opentrons.py) | 479 lines, the pattern to mirror |
| Liquid classes | [liquid_class.py](packages/core/src/cubos/instruments/pipette/liquid_class.py) | vendor-agnostic, reusable as-is |
| Registry | [registry.yaml](packages/core/src/cubos/instruments/registry.yaml) | one new `vendors:` entry |
| Test suite | [test_pipette.py](packages/core/tests/instruments/pipette/test_pipette.py) | 80 tests; mirror its shape |

**The API and Operator UI need no code changes.** `services/api` builds its
vendor list from `get_supported_vendors()` and its config-field schema from
`config_fields()`, which reflects over the driver's `__init__` signature and
reads `CONFIG_FIELD_CHOICES` ([registry.py:137](packages/core/src/cubos/instruments/registry.py:137)).
A new vendor plus a `CONFIG_FIELD_CHOICES = {"pipette_model": [...]}` class
attribute appears in the gantry editor automatically.

### 2.2 The protocol is already known — with a licensing caveat

`cnc-4-science` (AccelerationConsortium) ships a working 342-line Picus 2
driver at `examples/liquid_handling/tools/picus_driver.py`, plus a
serial-dilution demo that runs it against a Genmitsu 3018. That gives us
high confidence in the wire protocol, the mounting approach, and the fact
that gantry-driven tip pickup works.

> ### 🚩 F-0 — Licensing (HIGH). `cnc-4-science` is GPL-3.0; CubOS is MIT.
> The driver file, the custom tip-rack labware JSON, and the toolhead-mount
> STLs **cannot be copied or adapted into CubOS**. The wire protocol itself
> (command names, framing, baud rate) is unprotectable fact, but to keep
> provenance clean the CubOS driver should be written against Sartorius's own
> integration documentation. Sartorius markets an "open connectivity
> interface" for exactly this purpose but does not publish the spec — it has
> to be requested (§8). This constraint is already recorded in
> [cnc-4-science-vs-cubos.md](../cnc-4-science-vs-cubos.md): *"reimplement
> ideas, never copy code into CubOS."*

---

## 3. Hardware and protocol facts

### 3.1 Model matrix

From the [Picus 2 product datasheet](https://api.sartorius.com/document-hub/dam/download/235842/Electronic-Pipette-Picus-2-Product-Datasheet-en-Sartorius.pdf) (rev. 07|2024):

| Order no. | Ch | Range (µL) | Increment (µL) | Proposed CubOS key |
|---|---:|---|---:|---|
| LH-747021 | 1 | 0.5 – 10 | 0.01 | `picus2_1ch_10` |
| LH-747041 | 1 | 5 – 120 | 0.10 | `picus2_1ch_120` |
| LH-747061 | 1 | 10 – 300 | 0.20 | `picus2_1ch_300` |
| LH-747081 | 1 | 50 – 1,000 | 1.00 | `picus2_1ch_1000` |
| LH-747101 | 1 | 100 – 5,000 | 5.00 | `picus2_1ch_5000` |
| LH-747111 | 1 | 500 – 10,000 | 10.00 | `picus2_1ch_10000` |
| LH-747321 / 747421 | 8 / 12 | 0.5 – 10 | 0.01 | *deferred* (**F-11**) |
| LH-747341 / 747441 | 8 / 12 | 5 – 120 | 0.10 | *deferred* |
| LH-747361 / 747461 | 8 / 12 | 10 – 300 | 0.20 | *deferred* |
| LH-747391 / 747491 | 8 / 12 | 50 – 1,200 | 1.00 | *deferred* |

Unlike the Opentrons registry — where 8 of 10 models carry `# placeholder`
positions awaiting hardware calibration — **every Picus entry is a published
vendor figure**. There is nothing to calibrate on the pipette side. That is a
material advantage: a Picus model is usable the day it is registered.

Other relevant specs: Li-Po 3.7 V / 350 mAh, ~1 h charge, >1,000 pipetting
cycles per charge (>500 above 1,000 µL); electronic tip ejection; micro-USB
(charge **and** communication); Bluetooth 5.3 LE (BMD-350 module, ~10 m);
100 g / 210 mm for a 1-ch 300 µL body.

### 3.2 Wire protocol

Line-based JSON over serial, **230400 8N1**, CRLF-terminated. Frames carry a
monotonic sequence number so replies can be correlated:

```
{"no":7,"data":"RUN_ASPIRATE 500 5"}\r\n
```

A reply is zero or more envelope tokens (`ACK` / `BEGIN` / `END`), zero or
more data lines, then a terminal result token `<CODE> <no>`.

| Command | Purpose | Maps to |
|---|---|---|
| `AUTO 1` | enable async reporting | `connect()` |
| `ENABLE_MOTOR_CONTROL <0\|2>` | arm / release remote control | `connect()` / `disconnect()` |
| `RUN_INIT` | initialize piston, find home | `connect()`, `warm_up()` |
| `HOME` | piston to home position | `home()` |
| `RUN_ASPIRATE <µL> <1..9>` | aspirate | `aspirate()` |
| `RUN_DISPENSE <µL> <1..9>` | dispense | `dispense()` |
| `BLOW_OUT <go_home> <1..9> <delay_ms>` | expel residual | `blowout()` |
| `TIP_EJECT` | electronic ejector | `drop_tip()` |
| `GET_MODEL` / `GET_NOMINAL_VOLUME` / `GET_SERIAL` / `GET_VERSION` | identity | `connect()` cross-check |
| `GET_BATTERY_LEVEL` | charge state | `health_check()`, `get_status()` |

Result codes: `OK`, `FULL`, `SYNTAX_ERROR`, `ERROR_PARSING`,
`UNKNOWN_COMMAND`, `MISSING_PARAMETERS`, `ERR_RANGE_PARAMETERS`, `CHK_ERROR`,
`NOT_ALLOWED`, `FAILED`, `MOTOR_CONTROL_ABORTED`.

Two of these matter architecturally. `FULL` gives a hardware-side guard
against over-aspiration that the Opentrons firmware has no equivalent for.
`MOTOR_CONTROL_ABORTED` means remote control was dropped mid-run — see
**F-3**.

---

## 4. Method-by-method mapping

Every member of `BaseInstrument` + `PipetteInstrument`. "Parity" compares
against what `OpentronsPipette` actually delivers today.

| Member | Picus 2 implementation | Support | Parity |
|---|---|---|---|
| `connect()` | open port → `AUTO 1` → `ENABLE_MOTOR_CONTROL 2` (+confirm) → `RUN_INIT` → `GET_MODEL`/`GET_NOMINAL_VOLUME` cross-check → battery gate | ✅ full | **better** — can verify the configured model against the physical device; Opentrons cannot |
| `disconnect()` | `ENABLE_MOTOR_CONTROL 0`, close port | ✅ full | equal |
| `health_check()` | `GET_VERSION` round-trip (2 s) + battery read | ✅ full | **better** — surfaces charge state |
| `warm_up()` | `RUN_INIT` + `HOME` | ✅ full | equal |
| `calibrate()` | base no-op; CubOS contact calibration handles it | ✅ n/a | equal |
| `home()` | `RUN_INIT` on first call, else `HOME` | ✅ full | **better** — no 31 mm/55 mm short-travel retry hack needed |
| `prime(speed)` | **no analogue** — ensure init + `HOME`, set `_is_primed` | ⚠️ vacuous | **F-6** |
| `aspirate(vol, speed)` | `RUN_ASPIRATE <q(vol)> <s(speed)>` | ✅ full | volume quantized (**F-4**); `position_mm` unobservable (**F-5**) |
| `dispense(vol, speed)` | `RUN_DISPENSE <q(vol)> <s(speed)>` | ✅ full | same |
| `blowout(speed)` | `BLOW_OUT <go_home> <s> <delay_ms>` | ✅ full | **better** — real blow-out, not a plunger move to a hardcoded mm |
| `mix(vol, reps, speed)` | host-side aspirate/dispense loop ×`reps` | ⚠️ emulated | **F-7** — no atomic firmware mix |
| `pick_up_tip(speed)` | **no pipette command** — gantry Z-press seats the tip; driver sets `_has_tip` | ✅ full | equal (neither vendor senses the tip, **F-8**) |
| `drop_tip(speed)` | `TIP_EJECT`, clear tip extension | ✅ full | **better** — electronic ejector; no drop-position/return-to-prime dance |
| `get_status()` | bookkeeping + live `GET_BATTERY_LEVEL` | ⚠️ partial | **F-5** — `position_mm` / `is_homed` / `is_primed` are driver state |
| `attached_tip_extension` (property) | mirror Opentrons | ✅ full | equal |
| `set_attached_tip_extension()` | mirror Opentrons (validate finite ≥ 0) | ✅ full | equal |
| `clear_attached_tip_extension()` | mirror Opentrons | ✅ full | equal |
| `effective_depth` (property) | `depth + tip extension` | ✅ full | equal |
| `liquid_classes` / `correction_for()` | inherited; `build_liquid_classes(...)` in `__init__` | ✅ full | equal |
| `config` (property) | return the model's `PipetteConfig` | ✅ full | needs **F-2** refactor |
| `drip_stop(vol, speed)` | *Opentrons-only vendor extra, not on the interface and not called by the engine.* Optional parity via `BLOW_OUT` with repeated blow-out | ➖ optional | n/a |

### 4.1 Two required unit conversions

**Speed.** The interface passes `speed: float = 50.0` with no declared units,
and `OpentronsPipette` **discards it entirely** — it always sends
`_FIRMWARE_DEFAULT_SPEED = 0.0` because the firmware's `stepDelay` floor
makes small values ~16× slower than intended
([opentrons.py:39](packages/core/src/cubos/instruments/pipette/vendors/opentrons.py:38)).
Picus wants an integer 1–9. Proposed map, chosen so the interface default
lands on the vendor's own mid-scale default:

```python
speed_index = clamp(1 + round(speed / 100 * 8), 1, 9)   # 50.0 -> 5
```

Because existing protocols carry `speed: 50.0` values that have never meant
anything, this map must be documented in `docs/protocol-yaml.md` — otherwise
the first Picus protocol silently starts honouring a number nobody chose.

**Volume.** Quantize to the model increment before sending:

```python
q = round(volume_ul / increment) * increment
```

Reject (as `PipetteCommandError`) if `q` falls outside
`[min_volume, max_volume]`. See **F-4** for the accounting consequence.

---

## 5. Required CubOS core changes

Small and contained. Files, in dependency order:

**1. `packages/core/src/cubos/instruments/pipette/models.py`**

- `PipetteFamily`: add `PICUS2 = "PICUS2"`.
- **Split `PipetteConfig`** (**F-2**): keep `name`, `family`, `channels`,
  `max_volume`, `min_volume` on the base; add
  `volume_increment_ul: float = 0.0`; move `zero_position`,
  `prime_position`, `blowout_position`, `drop_tip_position`, `mm_to_ul` into
  a `PlungerPipetteConfig(PipetteConfig)` subclass used by `PIPETTE_MODELS`.
  `pipette_capacity()` isinstance-checks against `PipetteConfig`
  ([_liquid_transfer.py:41](packages/core/src/cubos/protocol_engine/commands/_liquid_transfer.py:41)),
  so the subclass keeps stroke-splitting and preflight working unchanged.
- Add `PICUS2_MODELS: dict[str, PipetteConfig]` (six 1-ch entries, §3.1).
- `PipetteStatus`: add `battery_percent: float | None = None`.
- `AspirateResult`: add `loaded_volume_ul: float | None = None`.

Both new fields default to `None`, so `OpentronsPipette` and all 80 existing
tests are unaffected.

**2. `exceptions.py`** — add `PipetteBatteryError(PipetteError)` and
`PipetteMotorControlError(PipetteError)` (for `MOTOR_CONTROL_ABORTED`).

**3. `vendors/sartorius.py`** (new, ~450 lines) — `SartoriusPicus2Pipette`.
Constructor mirrors `OpentronsPipette` plus: `pipette_model`, `port`,
`default_speed=5`, `blowout_delay_ms=3000`, `blowout_go_home=True`,
`min_battery_percent=20.0`, `verify_model=True`, `motor_control_mode=2`.
Full `offline=True` simulation path, as CubOS requires of every driver.

**4. `registry.yaml`** — add under `pipette.vendors`:

```yaml
      sartorius:
        module: cubos.instruments.pipette.vendors.sartorius
        class_name: SartoriusPicus2Pipette
```

**5. `pipette/__init__.py`** and **`vendors/__init__.py`** — export the class
and `PICUS2_MODELS`.

**6. Labware** (**F-9**) — new `sartorius_optifit_*` tip-rack definitions
under `packages/core/src/cubos/deck/labware/definitions/` plus entries in
that directory's `registry.yaml`, following
[ursa_tip_rack/TipRack.yaml](packages/core/src/cubos/deck/labware/definitions/ursa_tip_rack/TipRack.yaml).
`tip_length`, `drop_z`, and the calibration anchors must be measured on the
physical rack.

**7. Docs** — a `pipette` / `sartorius` YAML example in
[docs/gantry-setup.md:114](docs/gantry-setup.md:113), a table row in
[instruments/README.md:14](packages/core/src/cubos/instruments/README.md:14),
and the speed-map note in `docs/protocol-yaml.md`.

**8. Tests** — new `tests/instruments/pipette/test_picus2.py` mirroring the
Opentrons suite (fake-serial transcript fixtures, offline-path coverage,
every interface method). Two existing tests need updating:
`test_model_count` (asserts `len(PIPETTE_MODELS) == 10`) and
`test_all_models_have_valid_channels` (asserts `channels in (1, 8, 96)` —
would reject 12-channel models when those land).

---

## 5a. Operator intervention (resolves the F-1 workflow)

Prompting the operator is a **cross-cutting instrument capability**, not a
pipette feature. The Picus is just the first instrument that needs it; the
capper's sensor-confirm ladder and any future physical interlock have the same
shape. It therefore belongs on `BaseInstrument`, and its operator-facing half
belongs to the [Run Protocol UI](2026-08-17-run-protocol-ui-scope.md).

### The seam

CubOS already has the dependency-injection pattern for operator I/O:
[calibrate_gantry.py:97](packages/core/src/cubos/tools/calibrate_gantry.py:97)
injects `input_reader: Callable[[str], str]` and `output: Callable[[str], None]`
rather than calling `input()`. Mirror it:

```python
# cubos/instruments/operator_gate.py
class OperatorGate(Protocol):
    def request(self, *, instrument: str, action: str,
                message: str, timeout_s: float) -> None: ...
        # returns on confirm; raises OperatorDenied / OperatorTimeout otherwise
```

| Gate | Used by | Behavior |
|---|---|---|
| `ConsoleOperatorGate` | `run_protocol.py` on a TTY | prints, waits on injected `input_reader` |
| `RunEventOperatorGate` | `RunManager._execute` | emits event, blocks a `threading.Event`, woken by the ack endpoint |
| `AutoOperatorGate` | `offline=True` / `--mock` | auto-confirms; nothing physical happens |
| `DeniedOperatorGate` | **default** | raises immediately, naming the action a human would have had to take |

`DeniedOperatorGate` as the default is the whole design: an unwired gate is a
hard failure, never a skip.

> **Do not reuse the `breakpoint` command**
> ([pause.py:35](packages/core/src/cubos/protocol_engine/commands/pause.py:35)).
> It logs a warning and **returns** when `stdin` is not a TTY. Fine for "pause
> so I can look at the plate"; catastrophic as an arming gate, because a
> headless run would sail past it and then command motion on an unarmed
> pipette. It fails open in a codebase that otherwise fails closed.

### Wiring

Instruments are constructed purely from YAML kwargs, and
[`_validate_driver_kwargs`](packages/core/src/cubos/gantry/instrument_loader.py:80)
rejects any key the constructor does not accept — so the gate cannot arrive
through YAML. Use a post-construction `attach_operator_gate()` setter, plumbed
through `_instantiate_instruments` → `build_instrumented_gantry`. Convenient
side effect: `config_fields()` filters to `{str, int, float, bool}`, so a gate
object could never leak into the gantry editor's schema.

### Declare it so preflight can fail closed offline

Add `requires_operator_arming` as per-vendor metadata in
`instruments/registry.yaml`, alongside the existing
`calibration_mode: contact | non_contact`. Then `validate_setup` refuses a
headless run of a gantry containing a gate-requiring instrument — offline, with
no hardware touched.

This is the CubOS-idiomatic part, and the reason F-1 is manageable rather than
fatal: the requirement is **discovered before motion starts**, not forty
minutes into a run with liquid in the tip.

---

## 5b. What this means for the pipette interface

The useful result of this exercise is not the Picus mapping. It is that a
completely different actuation mechanism — vendor-owned motor, volume-native
commands, no position feedback — mapped onto the existing verbs **without
changing any of them**. That is strong evidence the verb set is genuinely
vendor-neutral, and it should not be touched.

`attached_tip_extension` / `effective_depth` also came through clean, and it is
worth naming why: it models the tool's *reach* as runtime geometry, separate
from the static mount `depth`. It describes a physical fact about the
instrument, not a fact about how the plunger works. Best-generalizing
abstraction in the module.

**Everything that broke broke for one reason: actuator mechanism leaked upward
into shared types.** Three places, all listed in §5:

1. `PipetteConfig` conflates **capability** (min/max volume, channels — every
   pipette has them) with **mechanism** (plunger positions, `mm_to_ul` — only a
   CubOS-driven stepper has them).
2. `PipetteStatus` reports **actuator internals** (`position_mm`, `is_primed`)
   where a protocol wants **pipetting state** (tip attached, volume loaded,
   ready). `loaded_volume_ul` is the vendor-neutral form of what
   `position_mm × mm_to_ul` was always a proxy for — it improves *both* drivers.
3. `speed: float = 50.0` has **no defined unit**, and the only existing driver
   discards it. Two vendors is the point where it must be defined: declare it as
   a normalized 0–100 percentage of the instrument's usable speed range, mapped
   to native units per driver. That also gives the Opentrons
   `_FIRMWARE_DEFAULT_SPEED` `TODO(iter)` a principled home.

### Decision: fit the mold, fix those three leaks, build nothing else

Two vendors is enough to see which abstractions are wrong and not enough to
design for the general case. Explicitly **declined for now**:

- **No capability-negotiation framework.** No `supports("prime")` for one
  vendor. `prime()` as a documented no-op is honest and free. If a third vendor
  also lacks it, the pattern is real and *then* it earns being modelled.
- **No abstract `PipetteTransport` layer.** Keep serial framing inside the
  vendor class; design it as a *seam* (so BLE can slot in per F-12) without
  promoting it to a shared abstraction.
- **No restructuring around Picus advanced modes.** Ask Sartorius whether
  reverse pipetting and multi-dispense are wire-addressable (F-13) before
  designing interface methods for them.

Rule to write into the interface docstring: **the interface describes what a
pipette does to liquid; the vendor class owns how its actuator gets there.**
Each of the three leaks violates it. Nothing else does.

---

## 6. Flags

Ordered by severity. **F-0** (licensing) is in §2.2.

### 🚩 F-1 — Arming remote motor control may need a human (HIGH)

`ENABLE_MOTOR_CONTROL 2` appears to require a confirmation on the pipette's
own screen before the host can drive the motor. The `cnc-4-science` driver
works around this by spamming synthetic softkey frames
(`{"no":N,"button":"TRIGGER_BUTTON_RIGHT"}`) every 400 ms until the pipette
returns `OK`. That is an undocumented behaviour and we do not know whether it
is firmware-version-stable or sanctioned by Sartorius.

If the confirmation must be a *physical* press, **unattended cold start is
impossible** and every `connect()` needs an operator at the bench. For CubOS
— whose whole value proposition includes overnight campaigns and the nightly
dispatcher — this is the single most important unknown.

*Mitigation:* implement the auto-confirm path with a bounded timeout and a
clear `PipetteConnectionError` telling the operator to press the right
softkey. Confirm the sanctioned mechanism with Sartorius (§8). Test whether
motor control survives a USB re-enumeration, so a mid-campaign reconnect
does not need re-arming.

The operator-facing half of this is designed in
[Run Protocol UI scope](2026-08-17-run-protocol-ui-scope.md) — see §5a below
for how the two fit together. The key result: because arming lives in
`connect()`, it lands in **preflight**, not mid-run, so the cost is one press
per session rather than one per command.

### 🚩 F-2 — `PipetteConfig` is plunger-shaped (HIGH, design)

Five of the ten `PipetteConfig` fields (`zero_position`, `prime_position`,
`blowout_position`, `drop_tip_position`, `mm_to_ul`) describe a stepper
pushing a plunger. None exist on a Picus. The alternative to the §5 split is
filling them with `0.0` sentinels, which is cheaper but writes meaningless
numbers into a shared type that the protocol engine reads. Given `mm_to_ul`
is only consumed inside the Opentrons driver and its own tests, the split is
low-risk and worth doing before a second volume-native vendor makes it
mandatory.

### 🚩 F-3 — `MOTOR_CONTROL_ABORTED` is a mid-run failure mode (MEDIUM-HIGH)

If anyone touches the pipette, or the device drops remote control for its own
reasons, commands start returning `MOTOR_CONTROL_ABORTED`. CubOS has no
comparable "the instrument revoked my authority" state today.

*Mitigation:* map it to a dedicated `PipetteMotorControlError`, fail closed
(never silently re-arm mid-protocol — the piston position after an abort is
unknown), and require an explicit reconnect. When it happens inside a
`transfer`, the engine's existing two-phase journal already marks the fluid
operation `reconciliation_required`, which is the correct outcome.

### 🚩 F-4 — Quantized volume vs. durable fluid accounting (MEDIUM)

Picus volumes are settable only in model increments (0.01 µL on the 10 µL
model, **10 µL on the 10 mL model**). CubOS commands arbitrary floats,
especially through liquid-class correction (`1.01x + 6.23`).

The subtle part: `_execute_transfer_stroke` calls
`pipette.aspirate(commanded_volume_ul, speed)` and **discards the return
value** — durable fluid state is committed from the journaled
`stroke_volume_ul`
([pipette.py:740](packages/core/src/cubos/protocol_engine/commands/pipette.py:734)).
So a driver-side quantization is invisible to the database. Worst case on the
10 mL model is ±5 µL per stroke, unrecorded.

Also worth noting: it is unconfirmed whether the wire protocol accepts
fractional µL at all. The `cnc-4-science` driver rounds to **integer µL**,
which would make the 0.5–10 µL model (0.01 µL increment) unusable. This needs
resolving before the small-volume models are registered.

*Mitigation:* quantize in the driver, return the quantized figure in
`AspirateResult.volume_ul`, and raise if the residual exceeds
`increment / 2`. Longer term, have the engine record the driver's returned
volume rather than the requested one — that is a pre-existing gap the
Opentrons driver simply never exposed.

### 🚩 F-5 — No piston-position, homed, or primed readback (MEDIUM)

The Picus exposes no position query. `PipetteStatus.position_mm`,
`is_homed`, `is_primed` and `AspirateResult.position_mm` therefore become
pure driver bookkeeping, lost on reconnect. Note `PipetteStatus.is_valid`
requires `position_mm >= 0`, so reporting a documented `0.0` is legal.

*Mitigation:* report `position_mm = 0.0` with an explicit docstring
("not observable on this vendor") and carry the real signal in the new
`loaded_volume_ul` field. Do **not** synthesize a fake millimetre figure
through a nominal `mm_to_ul` — that is fabricated precision in a field
operators will read. `connect()` always runs `RUN_INIT`, so a reconnect
starts from a known-empty piston regardless.

### 🚩 F-6 — `prime()` has no Picus analogue (MEDIUM)

On Opentrons, priming parks the plunger mid-travel so a later aspirate has
somewhere to go. The Picus manages its own piston reference and takes
absolute volumes, so there is nothing to pre-position. `prime()` reduces to
"ensure initialized + `HOME`", and `is_primed` degrades to meaning
"initialized".

This is the one interface method that **cannot be meaningfully implemented**.
It should be documented as a no-op rather than given a plausible-looking
fake. Low practical impact: nothing in `packages/core/src` calls `prime()`
outside `warm_up()` and the Opentrons `connect()`.

### 🚩 F-7 — `mix()` is emulated, not atomic (LOW-MEDIUM)

No firmware mix command; `mix()` becomes a host-side loop. A failure at
repetition 3 of 5 leaves liquid in the tip with no vendor-side recovery.

*Mitigation:* on exception, attempt a dispense-back plus `BLOW_OUT` before
re-raising. The engine's `mix` command already marks the operation
`reconciliation_required` on any exception
([pipette.py:372](packages/core/src/cubos/protocol_engine/commands/pipette.py:377)).

### 🚩 F-8 — No tip-attached sensing (LOW — pre-existing)

`PipetteStatus.has_tip` is bookkeeping, and a tip lost mid-run is
undetectable. Identical to the Opentrons driver, so no regression — but worth
stating explicitly since the Optiload spring cones make a *partially* seated
tip plausible on this hardware.

### 🚩 F-9 — No Sartorius tip-rack labware, and tips are long (MEDIUM)

CubOS ships one tip rack (`ursa_tip_rack`, 2×15, `tip_length: 59.3`).
Sartorius Optifit racks need new definitions, and the 5,000 µL model uses
**150 mm** tips. `attached_tip_extension` values of that magnitude flow
straight into the validation layer's `pipette_tip_extension` reachability and
collision checks, which have only ever seen ~59 mm.

Concrete pre-build check: pipette body 210 mm + 150 mm tip against the
target gantry's `factory_z_travel_mm` / `working_volume.z_max` (129 mm on
`cub_xl`). `cnc-4-science` needed 100 mm gantry spacers to fit this pipette
on a 3018. **Do not assume it drops onto an existing Cub without a Z-budget
calculation.** The toolhead clamp is a new Cubware part (their STLs are
GPL, per **F-0**).

### 🚩 F-10 — Battery is a failure mode CubOS has never modeled (MEDIUM)

>1,000 cycles per charge (>500 above 1,000 µL) is plenty for a shift and not
obviously plenty for a multi-day campaign. No CubOS instrument has ever had a
charge state.

*Mitigation:* the micro-USB port is **both** the comms and the charging port,
so a USB-tethered pipette charges while it runs — which is the main reason to
prefer USB over Bluetooth (see **F-12**). Additionally: gate protocol start on
`GET_BATTERY_LEVEL >= min_battery_percent` (fail closed with
`PipetteBatteryError`), surface `battery_percent` through `get_status()` to
the Operator UI, and log a warning on decline.

### 🚩 F-11 — Multichannel is blocked by CubOS, not by the Picus (MEDIUM)

The deck and protocol model addresses single wells. An 8-channel Picus
commanded to aspirate 100 µL moves 800 µL of liquid while durable fluid
state records one well. Registering 8/12-channel models would produce
silently wrong fluid accounting.

Note this is **pre-existing**: `p300_multi_gen2`, `flex_8channel_50` and
`flex_96channel_1000` are already in `PIPETTE_MODELS` with the same latent
problem. Worth a separate ticket; do not widen it here.

*Recommendation:* register the six single-channel models only. Add the
multichannel entries when the engine models `channels` (column-aware
addressing plus n-fold fluid accounting). Also remember
`test_all_models_have_valid_channels` asserts `channels in (1, 8, 96)` and
will need 12 added.

### 🚩 F-12 — Bluetooth transport is unverified (MEDIUM)

The manual specifies **Bluetooth 5.3 LE (BMD-350)**. The `cnc-4-science`
driver docstring claims the protocol "works identically for USB-CDC and
Bluetooth SPP" — but SPP is a Bluetooth *Classic* profile, so either that
claim is untested or the device also exposes Classic. BLE would need a GATT
characteristic pair, not a serial port, meaning a different transport layer
in the driver.

*Recommendation:* **ship USB-only for v1.** It is the validated path, it keeps
the battery charged (**F-10**), and it avoids a wireless dependency in a
metal enclosure. Design the driver's transport as a seam so BLE can be added
later without touching command logic. Physical caveat: micro-USB on a moving
gantry head needs strain relief / a drag chain — micro-USB is not a
flex-rated connector.

### 🚩 F-13 — Advanced Picus modes are out of interface scope (LOW — opportunity)

The Picus has 8 pipetting modes and 8 advanced functions: reverse pipetting,
multi-dispensing, diluting, sequential dispensing, multi-aspiration, titrate,
excess-volume adjustment, repeated blow-out. Whether any are reachable over
the wire is unknown; `PipetteInstrument` has no methods for them regardless.

Flagged as **upside, not a gap**: reverse pipetting and repeated blow-out are
exactly what viscous-liquid handling wants, which is Ursa's bioadhesives
domain. If Sartorius exposes them, they justify new optional interface
methods (`aspirate_reverse`, `multi_dispense`) — a follow-on feature, not part
of this scope.

---

## 7. Work breakdown

| Phase | Work | Est. |
|---|---|---|
| 0 | Request the Picus 2 connectivity spec from Sartorius (§8); resolve **F-0** provenance | 1 day elapsed, ~0 effort |
| 1 | `models.py` refactor (**F-2**), `PICUS2_MODELS`, new exceptions, new status/result fields; update the 2 affected existing tests | 0.5 day |
| 2 | `vendors/sartorius.py`: transport, framing, sequence numbers, result-code handling, full offline path | 1 day |
| 3 | Interface methods + speed map + volume quantization + battery gate + model cross-check | 0.5 day |
| 4 | `test_picus2.py` — fake-serial transcripts, offline coverage, every method, error paths | 1 day |
| 5 | Registry, exports, `docs/gantry-setup.md`, instruments README, protocol-yaml speed note | 0.5 day |
| 6 | Sartorius Optifit tip-rack labware definitions (**F-9**) | 0.5 day + measurement |
| 7 | Cubware toolhead mount + Z-budget check (**F-9**) | mechanical, parallel |
| 8 | Hardware bring-up: arming (**F-1**), fractional-µL question (**F-4**), tip-seating force, end-to-end serial dilution | 1–2 days at the bench |

**Software total: ~4 days.** Phases 1–5 can proceed before hardware arrives;
phase 8 is the gate on declaring the vendor supported.

Suggested first milestone: an offline-only `pipette/sartorius` that passes
`validate_setup` on the existing `pipette_tip_transfer` fixture with
`vendor: sartorius`. That exercises the whole engine path — stroke splitting,
tip-state modeling, reachability — with zero hardware.

---

## 8. Questions for Sartorius

Ask alongside the request for the open-connectivity interface specification:

1. **Arming (F-1):** what is the sanctioned way for host software to enable
   remote motor control? Is a device-side confirmation always required, and
   is there a configuration or dock that waives it for integrated use?
2. **Volume resolution (F-4):** does `RUN_ASPIRATE` / `RUN_DISPENSE` accept
   fractional µL, or only whole model increments? What are the argument units
   and valid ranges?
3. **State readback (F-5):** is there any piston-position, loaded-volume,
   initialized, or tip-present query?
4. **Motor control abort (F-3):** what triggers `MOTOR_CONTROL_ABORTED`, and
   what is the prescribed recovery?
5. **Advanced modes (F-13):** are reverse pipetting, multi-dispense, and
   repeated blow-out addressable over the wire?
6. **Bluetooth (F-12):** is the LE transport a GATT service, and is there a
   documented profile — or is USB the supported integration path?
7. **Duty cycle:** is continuous automated actuation within the warranty and
   the calibration interval? Sartorius sells a
   [Picus 2 Dispenser Module for OEM robotics](https://www.sartorius.com/en/products/oem/dispensing)
   — worth asking whether that variant is the correct product for a gantry
   rather than the handheld.

---

## Sources

- [Picus 2 Electronic Pipette — Product Datasheet (Sartorius, 07|2024)](https://api.sartorius.com/document-hub/dam/download/235842/Electronic-Pipette-Picus-2-Product-Datasheet-en-Sartorius.pdf)
- [Picus 2 Operating Instructions](https://www.pipettes.com/pub/media/pdf/sartorius-Picus-2-Electronic-Pipette-user-manual.pdf)
- [Picus 2 product page — open connectivity](https://www.sartorius.com/en/products/pipetting/electronic-pipettes/picus-2)
- [Picus 2 Dispenser Module (OEM / robotic liquid handling)](https://www.sartorius.com/en/products/oem/dispensing)
- [Picus 2 brochure](https://www.sartorius.com/resource/blob/1464246/86fbfd00002f8822ba73a1d79ce5fc88/electronic-pipetting-system-picus-2-brochure-en-sartorius-pd-1--data.pdf)
- `cnc-4-science` (AccelerationConsortium, **GPL-3.0** — reference only, see **F-0**):
  `examples/liquid_handling/tools/picus_driver.py`, `protocols/serial_dilution_demo.py`,
  `ASSEMBLY_INSTRUCTIONS.md`
- CubOS: `packages/core/src/cubos/instruments/pipette/`,
  `packages/core/src/cubos/protocol_engine/commands/pipette.py`,
  `packages/core/src/cubos/instruments/registry.py`
