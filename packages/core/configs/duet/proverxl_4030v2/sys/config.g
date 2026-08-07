; config.g — Genmitsu ProVerXL 4030 V2 on Duet 3 Mainboard 6XD, RRF 3.5+ standalone.
;
; Coordinate frame (CubOS AGENTS.md): FLB origin, +X right, +Y back, +Z up.
; Machine homes to the back-right-top corner = (Xmax, Ymax, Zmax), so RRF machine
; coordinates ARE the deck frame (positive space). G54 stays identity/available.
;
; Motors are the V2's integrated closed-loop NEMA 23 steppers: common-ground
; step/dir inputs plus an enabled-when-grounded enable input, wired per motor as
;   PUL -> D#_STEP_NEG, DIR -> D#_DIR_NEG, GND -> D#_GND, EN -> D#_EN_NEG.
; Microstepping/current live on the motor DIP switches, so there is deliberately
; no M906/M915/M350 here.

; --- General ---
G90                               ; absolute coordinates
G21                               ; millimetres
M453                              ; CNC mode

; --- Network / identity ---
M550 P"proverxl-6xd"
M552 P0.0.0.0 S1                  ; Ethernet, DHCP (DWC for setup/debug); the CubOS
                                  ; host link is USB serial and needs no config

; --- Axis-to-driver mapping ---
M584 X0.0 Y0.1:0.2 Z0.3           ; ganged Y, one endstop, no auto-square (the
                                  ; frame handles squaring). NOTE: harness labels
                                  ; are crossed vs channel order — physical Y2 is
                                  ; on driver 0.1, physical Y1 on driver 0.2.

; --- External driver channels ---
; T: step timing us (high:low:dir-setup:dir-hold). Motor driver specs are
;    unpublished — conservative start. TODO(iter): try T2.5:2.5:5:5 after clean
;    bench stepping.
; S: directions bench-verified 2026-07-31 (+X=right, +Y=back, +Z=up in the deck
;    frame). The Y motors are NOT mirrored — both run S1. Fix here, never in
;    host code.
; R: R1 bench-verified (motors move and hold). EN_NEG meter check (boot/M17/M18
;    and >30 s idle) still pending — hard-path e-stop remains mandatory.
M569 P0.0 S0 R1 T5:5:10:10        ; X (verified: +X = right)
M569 P0.1 S1 R1 T5:5:10:10        ; physical Y2 motor (verified: +Y = back)
M569 P0.2 S1 R1 T5:5:10:10        ; physical Y1 motor (verified: +Y = back)
M569 P0.3 S1 R1 T5:5:10:10        ; Z (verified: +Z = up)

; --- Steps/mm ---
; 1204 ball screws, 4 mm lead; stock 400 steps/mm implies 1/8 microstep on the
; motor DIPs. TODO(iter): confirm by measured travel (10 mm commanded = 10.0 mm).
M92 X400 Y400 Z400

; --- Motion limits ---
; X/Y tuned and bench-verified 2026-07-31 (repeatability held at ruler
; precision after tuning). Y is capped at 1800: a repeatable resonance band
; was found ~2100-2400 mm/min (shudder throughout the move, both sides,
; cleared below and above the band); 1800 is the proven ceiling, not yet
; investigated further (candidate causes: gantry/coupling stiffness).
; Z left at original conservative bring-up values — untuned given the
; screw-jam and connector-fault history on this axis today; revisit only
; after further mechanical inspection.
M203 X2400 Y1800 Z900             ; max speed, mm/min
M201 X450 Y450 Z150               ; acceleration, mm/s^2
M566 X400 Y400 Z120               ; max instantaneous speed change, mm/min

; --- Axis limits: CubOS calibration semantics ---
; M208 spans are the USABLE range after homing pull-off. The 3 mm pull-off
; reserve sits beyond each max (between soft limit and switch) and is not
; addressable coordinate space; homing files G92 the backed-off position to the
; M208 max. TODO(iter): replace nominal travel with measured usable span.
M208 S1 X0 Y0 Z0
M208 X400 Y300 Z110

; --- Endstops ---
; One input per axis: the min and max NO microswitches are wired in parallel,
; closing to ground at either end — hence the inverted pin. RRF only monitors
; endstops during homing moves, so min-end protection is soft limits only
; (M564 below); homing files abort if the switch is already closed since we
; cannot tell which end is pressed. Verify each with M119 before motor power.
M574 X2 S1 P"!io0.in"
M574 Y2 S1 P"!io1.in"
M574 Z2 S1 P"!io2.in"

; --- Behavior / safety ---
M564 S1 H1                        ; enforce soft limits; no motion before homing
M906 I100                         ; idle factor 100% — never drop enables at idle
                                  ; (RRF 3.6 rejects M84 S0; verify EN_NEG stays
                                  ; asserted >30 s after M17 during bring-up)

; --- Operator controls (momentary NO to ground; verify polarity, fix with "!") ---
M950 J0 C"!io3.in"                ; e-stop (soft path; the hard path is the NC
M581 P0 T0 S1 R0                  ;   contact in the 48 V motor feed)
M950 J1 C"!io5.in"                ; pause
M581 P1 T1 S1 R0                  ; trigger 1 = built-in pause (runs pause.g)
M950 J2 C"!io6.in"                ; resume
M581 P2 T2 S1 R0                  ; trigger2.g -> M24
M950 J3 C"!io4.in"                ; reset
M581 P3 T3 S1 R0                  ; trigger3.g -> M999

; --- Spindle: intentionally unconfigured (lab gantry; CubOS issues no M3/M5) ---

T-1                               ; no tool selected
