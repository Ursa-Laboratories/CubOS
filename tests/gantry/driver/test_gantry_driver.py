import inspect
import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
import math

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from gantry.coordinates import Coordinates
from gantry.gantry_driver.driver import Mill, wpos_pattern, mpos_pattern
from gantry.gantry_driver.exceptions import StatusReturnError

class TestCNCDriverLogic(unittest.TestCase):
    
    def test_regex_patterns(self):
        """Test that regex patterns correctly parse GRBL status strings."""
        
        # Test WPos pattern
        wpos_status = "<Idle|WPos:10.500,20.123,-5.000|FS:0,0|WCO:0,0,0>"
        match = wpos_pattern.search(wpos_status)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "10.500")
        self.assertEqual(match.group(2), "20.123")
        self.assertEqual(match.group(3), "-5.000")
        
        # Test MPos pattern
        mpos_status = "<Idle|MPos:-400.123,-299.999,-10.000|FS:0,0>"
        match = mpos_pattern.search(mpos_status)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "-400.123")
        self.assertEqual(match.group(2), "-299.999")
        self.assertEqual(match.group(3), "-10.000")
        
        # Test failure cases
        invalid_status = "<Idle|FS:0,0>"
        self.assertIsNone(wpos_pattern.search(invalid_status))
        self.assertIsNone(mpos_pattern.search(invalid_status))

    def test_mill_motion_api_has_no_driver_level_instrument_offsets(self):
        """Board owns instrument offsets; Mill only receives machine coordinates."""
        signature = inspect.signature(Mill.move_to)
        self.assertNotIn("instrument", signature.parameters)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_direct_move_are_axis_by_axis(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Direct moves emit X, Y, Z on separate G-code lines — never a
        combined ``G01 X… Y…`` interpolation. The mill must not command
        simultaneous multi-axis motion so callers own every straight
        segment of the path."""
        mill = Mill()

        current = Coordinates(0.0, 0.0, 0.0)
        target = Coordinates(10.0, 20.0, -5.0)
        commands = mill._build_direct_move(current, target)

        self.assertEqual(commands, [
            "G01 X10.0 F2000",
            "G01 Y20.0 F2000",
            "G01 Z-5.0 F2000",
        ])
        # Regression guard: no combined-XY command anywhere.
        self.assertFalse(any("Y" in c and "X" in c for c in commands))

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_direct_move_skips_unchanged_axes(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Only the axes that actually changed get a G-code line."""
        mill = Mill()

        current = Coordinates(0.0, 5.0, -5.0)
        target = Coordinates(10.0, 5.0, -5.0)  # only X changes
        commands = mill._build_direct_move(current, target)

        self.assertEqual(commands, ["G01 X10.0 F2000"])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_transit_move_lifts_traverses_descends(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Transit: lift → X → Y → (descend skipped when target_z == travel_z).

        Models an inter-well scan hop. X and Y always ship as separate
        G-code lines so no diagonal motion is ever commanded.
        """
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)  # well_i action z
        target = Coordinates(-110.0, -60.0, -85.0)   # well_j approach z
        commands = mill._build_transit_move(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",    # lift
            "G01 X-110.0 F2000",   # X alone
            "G01 Y-60.0 F2000",    # Y alone
            # target.z == travel_z, final descent skipped.
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_transit_move_skips_lift_when_already_at_travel_z(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Already at travel_z: no lift, just X (Y unchanged) then descent."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -85.0)
        target = Coordinates(-110.0, -50.0, -90.0)  # Y unchanged
        commands = mill._build_transit_move(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 X-110.0 F2000",
            "G01 Z-90.0 F2000",
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_transit_move_skips_xy_when_target_xy_matches_current(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Same-XY transit: lift then descend — neither X nor Y emits."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)
        target = Coordinates(-100.0, -50.0, -90.0)
        commands = mill._build_transit_move(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",
            "G01 Z-90.0 F2000",
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_build_transit_move_emits_all_four_steps(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Lift → X → Y → descend, all four fire when every axis changes
        and travel_z differs from both current.z and target.z."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)
        target = Coordinates(-110.0, -60.0, -90.0)
        commands = mill._build_transit_move(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",    # lift
            "G01 X-110.0 F2000",   # X alone
            "G01 Y-60.0 F2000",    # Y alone
            "G01 Z-90.0 F2000",    # descend
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_move_to_uses_coordinates_directly(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.current_coordinates = MagicMock(
            return_value=Coordinates(-100.0, -50.0, -78.0),
        )
        mill.execute_command = MagicMock()

        mill.move_to(
            x_coordinate=-110.0,
            y_coordinate=-60.0,
            z_coordinate=-90.0,
        )

        mill.execute_command.assert_any_call("G01 X-110.0 F2000")
        mill.execute_command.assert_any_call("G01 Y-60.0 F2000")
        mill.execute_command.assert_any_call("G01 Z-90.0 F2000")

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_move_to_with_travel_z_emits_ordered_commands(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """End-to-end: move_to(..., travel_z=...) routes
        through _build_transit_move and emits lift → X → Y →
        descend in order. The emitted travel_z matches the input."""
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.current_coordinates = MagicMock(
            return_value=Coordinates(-100.0, -50.0, -78.0),
        )

        sent = []
        mill.execute_command = lambda cmd: sent.append(cmd) or "ok"

        mill.move_to(
            x_coordinate=-110.0, y_coordinate=-60.0, z_coordinate=-90.0,
            travel_z=-85.0,
        )

        self.assertEqual(sent, [
            "G01 Z-85.0 F2000",
            "G01 X-110.0 F2000",
            "G01 Y-60.0 F2000",
            "G01 Z-90.0 F2000",
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_move_to_rejects_non_finite_motion_inputs(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """The low-level driver must not format NaN/Inf into G-code."""
        cases = [
            {"x_coordinate": math.nan, "y_coordinate": 0.0, "z_coordinate": 0.0},
            {"x_coordinate": 0.0, "y_coordinate": math.inf, "z_coordinate": 0.0},
            {"x_coordinate": 0.0, "y_coordinate": 0.0, "z_coordinate": -math.inf},
            {
                "x_coordinate": 0.0,
                "y_coordinate": 0.0,
                "z_coordinate": 0.0,
                "travel_z": math.nan,
            },
        ]

        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                mill = Mill()
                mill.current_coordinates = MagicMock(
                    return_value=Coordinates(0.0, 0.0, 0.0),
                )
                mill.execute_command = MagicMock()

                with self.assertRaisesRegex(ValueError, "finite"):
                    mill.move_to(**kwargs)

                mill.execute_command.assert_not_called()

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.time.time', side_effect=[0.0, 2.0])
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_wait_for_completion_raises_on_timeout(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_time, mock_sleep,
    ):
        mill = Mill()
        mill.current_status = MagicMock(return_value="<Hold|WPos:0,0,0|FS:0,0>")

        with self.assertRaises(StatusReturnError):
            mill._wait_until_idle(
                "<Hold|WPos:0,0,0|FS:0,0>", timeout=1,
            )

    @patch('gantry.gantry_driver.driver.time.time', side_effect=[0.0, 6.0])
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_grbl_settings_command_times_out_without_ok(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_time,
    ):
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.ser_mill.readline.return_value = b"$20=1\n"

        with self.assertRaisesRegex(Exception, "Timed out"):
            mill.execute_command("$$")

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.time.time', side_effect=[0.0, 2.0])
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_home_raises_on_timeout(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_time, mock_sleep,
    ):
        mill = Mill()
        mill.execute_command = MagicMock()
        mill.current_status = MagicMock(return_value="<Run|WPos:0,0,0|FS:0,0>")

        with self.assertRaises(StatusReturnError):
            mill.home(timeout=1)

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.time.time', side_effect=[0.0, 0.2, 0.4])
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_home_retries_transient_status_failures(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_time, mock_sleep,
    ):
        mill = Mill()
        mill.execute_command = MagicMock()
        mill.current_status = MagicMock(
            side_effect=[
                StatusReturnError("Failed to get status from the mill"),
                "<Idle|WPos:0,0,0|FS:0,0>",
            ]
        )

        mill.home(timeout=1)

        self.assertTrue(mill.homed)
        self.assertEqual(mill.current_status.call_count, 2)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_mock_connection(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test connecting with mocked serial port."""
        mock_serial_instance = MagicMock()
        mock_serial_instance.is_open = True
        mock_serial.return_value = mock_serial_instance
        
        # Mock the locate_over_serial to return our mock
        with patch.object(Mill, '_locate_over_serial', return_value=(mock_serial_instance, '/dev/test')):
            mill = Mill()
            mill.read_config = MagicMock()
            mill.clear_buffers = MagicMock()
            mill.enforce_wpos_mode = MagicMock()
            mill.set_feed_rate = MagicMock()
            mill.seed_wco = MagicMock()
            mill.connect(port='/dev/test')
            
            self.assertTrue(mill.active_connection)
            self.assertEqual(mill.ser_mill, mock_serial_instance)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_read_grbl_settings_reads_live_controller(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that read_grbl_settings issues a live $$ read."""
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.ser_mill.is_open = True
        mill.execute_command = MagicMock(return_value={"$130": "400.000"})

        settings = mill.read_grbl_settings()

        mill.execute_command.assert_called_once_with("$$")
        self.assertEqual(settings["$130"], "400.000")
        self.assertEqual(mill.config["$130"], "400.000")

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_current_coordinates_does_not_require_homing_pull_off_setting(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_sleep,
    ):
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="<Idle|WPos:1.000,2.000,3.000|FS:0,0>")
        mill.config = {"$10": "0"}

        coords = mill.current_coordinates()

        self.assertEqual(coords, Coordinates(1.0, 2.0, 3.0))

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_enforce_wpos_mode_sets_ten_to_zero(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that enforce_wpos_mode sends $10=0 when not already set."""
        mill = Mill()
        mock_ser = MagicMock()
        mill.ser_mill = mock_ser
        mill.config["$10"] = "1"

        # Mock execute_command to track calls
        mill.execute_command = MagicMock()
        mill.enforce_wpos_mode()

        mill.execute_command.assert_any_call("$10=0")
        mill.execute_command.assert_any_call("G90")
        self.assertEqual(mill.config["$10"], "0")

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_enforce_wpos_mode_skips_when_already_zero(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that enforce_wpos_mode does not re-send $10=0 if already set."""
        mill = Mill()
        mill.config["$10"] = "0"
        mill.execute_command = MagicMock()

        mill.enforce_wpos_mode()

        calls = [str(c) for c in mill.execute_command.call_args_list]
        self.assertNotIn("call('$10=0')", calls)
        mill.execute_command.assert_called_with("G90")

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_jog_raises_when_not_connected(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that jog raises MillConnectionError when ser_mill is None."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = None
        with self.assertRaises(MillConnectionError):
            mill.jog(x=1.0)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_jog_raises_on_alarm_response(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that jog treats alarm responses as failed motion."""
        from gantry.gantry_driver.exceptions import CommandExecutionError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="<Alarm|WPos:0,0,0|Pn:Y>")

        with self.assertRaises(CommandExecutionError):
            mill.jog(y=-1.0)

        mill.ser_mill.write.assert_called_once()

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_jog_raises_on_check_limits_response(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that GRBL check-limits messages are treated as failed jogs."""
        from gantry.gantry_driver.exceptions import CommandExecutionError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="[MSG:Check Limits]\nok")

        with self.assertRaises(CommandExecutionError):
            mill.jog(y=-1.0)

        mill.ser_mill.write.assert_called_once()

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_jog_cancel_raises_when_not_connected(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that jog_cancel raises MillConnectionError when ser_mill is None."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = None
        with self.assertRaises(MillConnectionError):
            mill.jog_cancel()

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_unlock_raises_when_not_connected(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that unlock ($X) raises when ser_mill is None."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = None
        with self.assertRaises(MillConnectionError):
            mill.unlock()

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_soft_reset_raises_when_not_connected(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that soft_reset raises when ser_mill is None."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = None
        with self.assertRaises(MillConnectionError):
            mill.soft_reset()

    # ── Silent-failure regression guards ────────────────────────────────

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_enforce_wpos_mode_propagates_g90_failure(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """A failed G90 must raise — silent fallthrough risks relative-motion bugs."""
        from gantry.gantry_driver.exceptions import CommandExecutionError
        mill = Mill()
        mill.config["$10"] = "0"
        mill.execute_command = MagicMock(
            side_effect=CommandExecutionError("G90 rejected")
        )

        with self.assertRaises(CommandExecutionError):
            mill.enforce_wpos_mode()

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_query_raw_status_raises_on_serial_error(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_sleep,
    ):
        """OSError on transport must surface, not be flattened to ''."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.ser_mill.is_open = True
        mill.ser_mill.write.side_effect = OSError("port disappeared")

        with self.assertRaises(MillConnectionError):
            mill.query_raw_status()

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_query_raw_status_returns_empty_only_when_disconnected(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        mill = Mill()
        mill.ser_mill = None
        self.assertEqual(mill.query_raw_status(), "")

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_current_status_raises_instead_of_returning_empty_string(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """No more interactive-mode `return ""` after alarm/error detection."""
        from gantry.gantry_driver.exceptions import StatusReturnError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="")
        mill.ser_mill.readlines.return_value = [b"<Alarm|MPos:0,0,0>\n"]

        with self.assertRaises(StatusReturnError):
            mill.current_status()

    @patch('gantry.gantry_driver.driver.time.sleep')
    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_execute_command_error22_is_bounded(
        self, mock_cmd_logger, mock_mill_logger, mock_serial, mock_sleep,
    ):
        """Persistent error:22 must terminate after ERROR_22_MAX_RETRIES, not recurse."""
        from gantry.gantry_driver.driver import ERROR_22_MAX_RETRIES
        from gantry.gantry_driver.exceptions import CommandExecutionError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="error:22\nok")
        mill._wait_until_idle = MagicMock(return_value="error:22\nok")
        mill.set_feed_rate = MagicMock()

        with self.assertRaises(CommandExecutionError):
            mill.execute_command("G01 X10")

        # set_feed_rate is called once per retry attempt (not including the final
        # giving-up attempt that raises).
        self.assertEqual(mill.set_feed_rate.call_count, ERROR_22_MAX_RETRIES)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_execute_command_logs_even_when_suppress_errors(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """suppress_errors only demotes log level — it never produces a silent path."""
        from gantry.gantry_driver.exceptions import CommandExecutionError
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill._read_serial = MagicMock(return_value="error:9\nok")
        mill._wait_until_idle = MagicMock(return_value="error:9\nok")
        mill.logger = MagicMock()

        with self.assertRaises(CommandExecutionError):
            mill.execute_command("G01 X10", suppress_errors=True)

        # Every failure must produce at least one log call.
        self.assertTrue(mill.logger.log.called or mill.logger.error.called)


if __name__ == '__main__':
    unittest.main()
