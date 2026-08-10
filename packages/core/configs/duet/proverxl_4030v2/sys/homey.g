; homey.g — home Y to back (Ymax). Both Y motors move ganged and stop together
; on the single shared switch; no auto-squaring (the frame handles squaring).
if sensors.endstops[1].triggered
  abort "Y is on a limit switch — jog it off manually, then re-home"
M400
G91
G1 H1 Y310 F1200          ; seek back (300 nominal + 10 overshoot)
G1 Y-5 F1200
G1 H1 Y10 F300
G1 Y-3 F600               ; pull-off — reserve, not usable space
G90
G92 Y300                  ; TODO(iter): update after travel measurement
