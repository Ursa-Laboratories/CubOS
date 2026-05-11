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
        signature = inspect.signature(Mill.move_to_position)
        self.assertNotIn("instrument", signature.parameters)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_generate_movement_commands_are_axis_by_axis(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Direct moves emit X, Y, Z on separate G-code lines — never a
        combined ``G01 X… Y…`` interpolation. The mill must not command
        simultaneous multi-axis motion so callers own every straight
        segment of the path."""
        mill = Mill()

        current = Coordinates(0.0, 0.0, 0.0)
        target = Coordinates(10.0, 20.0, -5.0)
        commands = mill._generate_movement_commands(current, target)

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
    def test_generate_movement_commands_skips_unchanged_axes(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Only the axes that actually changed get a G-code line."""
        mill = Mill()

        current = Coordinates(0.0, 5.0, -5.0)
        target = Coordinates(10.0, 5.0, -5.0)  # only X changes
        commands = mill._generate_movement_commands(current, target)

        self.assertEqual(commands, ["G01 X10.0 F2000"])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_generate_transit_commands_lifts_traverses_descends(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Transit: lift → X → Y → (descend skipped when target_z == travel_z).

        Models an inter-well scan hop. X and Y always ship as separate
        G-code lines so no diagonal motion is ever commanded.
        """
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)  # well_i action z
        target = Coordinates(-110.0, -60.0, -85.0)   # well_j approach z
        commands = mill._generate_transit_commands(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",    # lift
            "G01 X-110.0 F2000",   # X alone
            "G01 Y-60.0 F2000",    # Y alone
            # target.z == travel_z, final descent skipped.
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_generate_transit_commands_skips_lift_when_already_at_travel_z(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Already at travel_z: no lift, just X (Y unchanged) then descent."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -85.0)
        target = Coordinates(-110.0, -50.0, -90.0)  # Y unchanged
        commands = mill._generate_transit_commands(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 X-110.0 F2000",
            "G01 Z-90.0 F2000",
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_generate_transit_commands_skips_xy_when_target_xy_matches_current(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Same-XY transit: lift then descend — neither X nor Y emits."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)
        target = Coordinates(-100.0, -50.0, -90.0)
        commands = mill._generate_transit_commands(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",
            "G01 Z-90.0 F2000",
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_generate_transit_commands_emits_all_four_steps(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """Lift → X → Y → descend, all four fire when every axis changes
        and travel_z differs from both current.z and target.z."""
        mill = Mill()

        current = Coordinates(-100.0, -50.0, -78.0)
        target = Coordinates(-110.0, -60.0, -90.0)
        commands = mill._generate_transit_commands(current, target, travel_z=-85.0)

        self.assertEqual(commands, [
            "G01 Z-85.0 F2000",    # lift
            "G01 X-110.0 F2000",   # X alone
            "G01 Y-60.0 F2000",    # Y alone
            "G01 Z-90.0 F2000",    # descend
        ])

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_move_to_position_uses_coordinates_directly(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.current_coordinates = MagicMock(
            return_value=Coordinates(-100.0, -50.0, -78.0),
        )
        mill.execute_command = MagicMock()

        mill.move_to_position(
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
    def test_move_to_position_with_travel_z_emits_ordered_commands(
        self, mock_cmd_logger, mock_mill_logger, mock_serial,
    ):
        """End-to-end: move_to_position(..., travel_z=...) routes
        through _generate_transit_commands and emits lift → X → Y →
        descend in order. The emitted travel_z matches the input."""
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.current_coordinates = MagicMock(
            return_value=Coordinates(-100.0, -50.0, -78.0),
        )

        sent = []
        mill.execute_command = lambda cmd: sent.append(cmd) or "ok"

        mill.move_to_position(
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
    def test_move_to_position_rejects_non_finite_motion_inputs(
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
                    mill.move_to_position(**kwargs)

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
            mill._Mill__wait_for_completion(
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
        
        # Mock the locate_mill_over_serial to return our mock
        with patch.object(Mill, 'locate_mill_over_serial', return_value=(mock_serial_instance, '/dev/test')):
            mill = Mill()
            mill.read_mill_config = MagicMock()
            mill.read_working_volume = MagicMock()
            mill.clear_buffers = MagicMock()
            mill._enforce_wpos_mode = MagicMock()
            mill.set_feed_rate = MagicMock()
            mill._seed_wco = MagicMock()
            mill.connect_to_mill(port='/dev/test')
            
            self.assertTrue(mill.active_connection)
            self.assertEqual(mill.ser_mill, mock_serial_instance)

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_grbl_settings_reads_live_controller(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that grbl_settings issues a live $$ read."""
        mill = Mill()
        mill.ser_mill = MagicMock()
        mill.ser_mill.is_open = True
        mill.execute_command = MagicMock(return_value={"$130": "400.000"})

        settings = mill.grbl_settings()

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
        mill.read = MagicMock(return_value="<Idle|WPos:1.000,2.000,3.000|FS:0,0>")
        mill.config = {"$10": "0"}

        coords = mill.current_coordinates()

        self.assertEqual(coords, Coordinates(1.0, 2.0, 3.0))

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_enforce_wpos_mode_sets_ten_to_zero(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that _enforce_wpos_mode sends $10=0 when not already set."""
        mill = Mill()
        mock_ser = MagicMock()
        mill.ser_mill = mock_ser
        mill.config["$10"] = "1"

        # Mock execute_command to track calls
        mill.execute_command = MagicMock()
        mill._enforce_wpos_mode()

        mill.execute_command.assert_any_call("$10=0")
        mill.execute_command.assert_any_call("G90")
        self.assertEqual(mill.config["$10"], "0")

    @patch('gantry.gantry_driver.driver.serial.Serial')
    @patch('gantry.gantry_driver.driver.set_up_mill_logger')
    @patch('gantry.gantry_driver.driver.set_up_command_logger')
    def test_enforce_wpos_mode_skips_when_already_zero(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that _enforce_wpos_mode does not re-send $10=0 if already set."""
        mill = Mill()
        mill.config["$10"] = "0"
        mill.execute_command = MagicMock()

        mill._enforce_wpos_mode()

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
        mill.read = MagicMock(return_value="<Alarm|WPos:0,0,0|Pn:Y>")

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
        mill.read = MagicMock(return_value="[MSG:Check Limits]\nok")

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
    def test_reset_raises_when_not_connected(self, mock_cmd_logger, mock_mill_logger, mock_serial):
        """Test that reset (unlock) raises when ser_mill is None."""
        from gantry.gantry_driver.exceptions import MillConnectionError
        mill = Mill()
        mill.ser_mill = None
        with self.assertRaises(MillConnectionError):
            mill.reset()

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


if __name__ == '__main__':
    unittest.main()
