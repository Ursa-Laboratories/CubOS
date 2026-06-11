# Appendix

## WPos And Soft Limits

Calibration uses GRBL WPos in the CubOS deck frame. It sets `$10=0` before
homing so status reports contain WPos.

`working_volume` is usable deck/WPos space after homing pull-off.
`grbl_settings.max_travel_x/y/z` mirrors GRBL `$130/$131/$132` and includes
the `$27` pull-off reserve. Do not add the pull-off reserve to
`working_volume`.

Example with `$27=10` and homed WPos `Z=91`:

```yaml
working_volume:
  z_max: 91.0
grbl_settings:
  homing_pull_off: 10.0
  max_travel_z: 101.0
```
