; homex.g — home X to right (Xmax). Home Z first (homeall enforces order).
if sensors.endstops[0].triggered
  abort "X is on a limit switch — jog it off manually, then re-home"
M400
G91
G1 H1 X410 F1200          ; seek right (400 nominal + 10 overshoot)
G1 X-5 F1200
G1 H1 X10 F300
G1 X-3 F600               ; pull-off — reserve, not usable space
G90
G92 X400                  ; TODO(iter): update after travel measurement
