; homez.g — home Z to top (Zmax). Run first, always.
; Shared min/max switch channel: if it is already closed we cannot tell which
; end, so refuse to home rather than guess.
if sensors.endstops[2].triggered
  abort "Z is on a limit switch — jog it off manually, then re-home"
M400
G91                       ; relative
G1 H1 Z120 F1200          ; seek up to switch (110 nominal + 10 overshoot)
G1 Z-5 F1200              ; retract clear of switch
G1 H1 Z10 F300            ; slow re-probe for repeatability
G1 Z-3 F600               ; pull-off — reserve, not usable space
G90
G92 Z110                  ; usable Zmax at backed-off point.
                          ; TODO(iter): update after travel measurement
