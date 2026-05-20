import unittest
from unittest.mock import patch

from gantry.errors import (
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)
from gantry.gantry import Gantry


class TestGantry(unittest.TestCase):
    def setUp(self):
        self.config = {"serial_port": "/dev/tty.usbserial"}

    @patch("gantry.gantry.Mill")
    def test_connect_auto_scans_even_with_configured_port(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.connect()
        mock_mill.connect.assert_called_with(port=None)

    @patch("gantry.gantry.Mill")
    def test_connect_accepts_explicit_port_override(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.connect(port="/dev/tty.usbserial-130")
        mock_mill.connect.assert_called_with(port="/dev/tty.usbserial-130")

    @patch("gantry.gantry.Mill")
    def test_move_delegates_to_mill_move_to(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.move_to(10, 20, 30)
        mock_mill.move_to.assert_called_with(
            x_coordinate=10.0,
            y_coordinate=20.0,
            z_coordinate=30.0,
            travel_z=None,
        )

    @patch("gantry.gantry.Mill")
    def test_move_with_travel_z_passes_through_deck_frame_z(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.move_to(10, 20, 30, travel_z=50)
        mock_mill.move_to.assert_called_with(
            x_coordinate=10.0,
            y_coordinate=20.0,
            z_coordinate=30.0,
            travel_z=50.0,
        )

    @patch("gantry.gantry.Mill")
    def test_is_healthy(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.active_connection = True
        mock_mill.ser_mill.is_open = True
        mock_mill.current_status.return_value = "<Idle|MPos:0,0,0|FS:0,0>"
        gantry = Gantry(config=self.config)
        self.assertTrue(gantry.is_healthy())

        mock_mill.current_status.return_value = "<Alarm|MPos:0,0,0|FS:0,0>"
        self.assertFalse(gantry.is_healthy())

    @patch("gantry.gantry.Mill")
    def test_connect_raises_mill_connection_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.connect.side_effect = MillConnectionError("no port")
        gantry = Gantry(config=self.config)
        with self.assertRaises(MillConnectionError):
            gantry.connect()

    @patch("gantry.gantry.Mill")
    def test_connect_does_not_catch_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.connect.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.connect()

    @patch("gantry.gantry.Mill")
    def test_disconnect_reraises_mill_connection_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.disconnect.side_effect = MillConnectionError("port busy")
        gantry = Gantry(config=self.config)
        with self.assertRaises(MillConnectionError):
            gantry.disconnect()

    @patch("gantry.gantry.Mill")
    def test_disconnect_does_not_catch_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.disconnect.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.disconnect()

    @patch("gantry.gantry.Mill")
    def test_is_healthy_returns_false_on_status_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.active_connection = True
        mock_mill.ser_mill.is_open = True
        mock_mill.current_status.side_effect = StatusReturnError("bad status")
        gantry = Gantry(config=self.config)
        self.assertFalse(gantry.is_healthy())

    @patch("gantry.gantry.Mill")
    def test_is_healthy_returns_false_on_connection_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.active_connection = True
        mock_mill.ser_mill.is_open = True
        mock_mill.current_status.side_effect = MillConnectionError("lost")
        gantry = Gantry(config=self.config)
        self.assertFalse(gantry.is_healthy())

    @patch("gantry.gantry.Mill")
    def test_is_healthy_propagates_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.active_connection = True
        mock_mill.ser_mill.is_open = True
        mock_mill.current_status.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.is_healthy()

    @patch("gantry.gantry.Mill")
    def test_home_raises_on_connection_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.home.side_effect = MillConnectionError("homing failed")
        gantry = Gantry(config=self.config)
        with self.assertRaises(MillConnectionError):
            gantry.home()

    @patch("gantry.gantry.Mill")
    def test_home_raises_on_status_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.home.side_effect = StatusReturnError("alarm")
        gantry = Gantry(config=self.config)
        with self.assertRaises(StatusReturnError):
            gantry.home()

    @patch("gantry.gantry.Mill")
    def test_home_does_not_catch_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.home.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.home()

    @patch("gantry.gantry.Mill")
    def test_home_uses_standard_grbl_homing_by_default(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.home()
        mock_mill.home.assert_called_once_with()

    @patch("gantry.gantry.Mill")
    def test_home_raises_on_unknown_strategy(self, mock_mill_cls):
        gantry = Gantry(config={"cnc": {"homing_strategy": "nonexistent"}})
        with self.assertRaises(ValueError):
            gantry.home()

    @patch("gantry.gantry.Mill")
    def test_prepare_for_protocol_run_unlocks_alarm_and_restores_state(
        self, mock_mill_cls
    ):
        mock_mill = mock_mill_cls.return_value
        mock_mill.query_raw_status.side_effect = [
            "<Alarm|WPos:0,0,0|FS:0,0>",
            "<Idle|WPos:0,0,0|FS:0,0>",
            "<Idle|WPos:0,0,0|FS:0,0>",
        ]
        mock_mill.read_grbl_settings.return_value = {}
        gantry = Gantry(config=self.config)

        gantry.prepare_for_protocol_run()

        mock_mill.soft_reset_and_unlock.assert_called_once()
        mock_mill.read_config.assert_called_once()
        mock_mill.clear_buffers.assert_called_once()
        mock_mill.enforce_wpos_mode.assert_called_once()
        mock_mill.set_feed_rate.assert_called_once()
        mock_mill.seed_wco.assert_called_once()

    @patch("gantry.gantry.Mill")
    def test_prepare_for_protocol_run_noops_when_not_in_alarm(
        self, mock_mill_cls
    ):
        mock_mill = mock_mill_cls.return_value
        mock_mill.query_raw_status.return_value = "<Idle|WPos:0,0,0|FS:0,0>"
        gantry = Gantry(config=self.config)

        gantry.prepare_for_protocol_run()

        mock_mill.soft_reset_and_unlock.assert_not_called()
        mock_mill.read_config.assert_not_called()

    @patch("gantry.gantry.Mill")
    def test_prepare_for_protocol_run_raises_if_alarm_persists(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.query_raw_status.side_effect = [
            "<Alarm|WPos:0,0,0|FS:0,0>",
            "<Idle|WPos:0,0,0|FS:0,0>",
            "<Alarm|WPos:0,0,0|FS:0,0>",
        ]
        mock_mill.read_grbl_settings.return_value = {}
        gantry = Gantry(config=self.config)

        with self.assertRaises(MillConnectionError):
            gantry.prepare_for_protocol_run()

    @patch("gantry.gantry.Mill")
    def test_move_to_raises_on_command_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.move_to.side_effect = CommandExecutionError("move failed")
        gantry = Gantry(config=self.config)
        with self.assertRaises(CommandExecutionError):
            gantry.move_to(10, 20, 30)

    @patch("gantry.gantry.Mill")
    def test_move_to_does_not_catch_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.move_to.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.move_to(10, 20, 30)

    @patch("gantry.gantry.Mill")
    def test_get_status_raises_on_status_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.current_status.side_effect = StatusReturnError("bad")
        gantry = Gantry(config=self.config)
        with self.assertRaises(StatusReturnError):
            gantry.get_status()

    @patch("gantry.gantry.Mill")
    def test_get_status_propagates_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.current_status.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.get_status()

    @patch("gantry.gantry.Mill")
    def test_stop_raises_on_known_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.stop.side_effect = CommandExecutionError("stop failed")
        gantry = Gantry(config=self.config)
        with self.assertRaises(CommandExecutionError):
            gantry.stop()

    @patch("gantry.gantry.Mill")
    def test_stop_propagates_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.stop.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.stop()

    @patch("gantry.gantry.Mill")
    def test_get_coordinates_raises_on_known_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.current_coordinates.side_effect = LocationNotFound()
        gantry = Gantry(config=self.config)
        with self.assertRaises(LocationNotFound):
            gantry.get_coordinates()

    @patch("gantry.gantry.Mill")
    def test_get_coordinates_propagates_unexpected_errors(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.current_coordinates.side_effect = RuntimeError("unexpected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(RuntimeError):
            gantry.get_coordinates()

    @patch("gantry.gantry.Mill")
    def test_jog_cancel_raises_on_connection_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.jog_cancel.side_effect = MillConnectionError("not connected")
        gantry = Gantry(config=self.config)
        with self.assertRaises(MillConnectionError):
            gantry.jog_cancel()

    @patch("gantry.gantry.Mill")
    def test_get_position_info_raises_on_error(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.current_coordinates.side_effect = StatusReturnError("fail")
        gantry = Gantry(config=self.config)
        with self.assertRaises(StatusReturnError):
            gantry.get_position_info()

    @patch("gantry.gantry.Mill")
    def test_extract_status_returns_idle_from_grbl_string(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.last_status = "<Idle|WPos:0,0,0|FS:0,0>"
        gantry = Gantry(config=self.config)
        self.assertEqual(gantry._extract_status(), "Idle")

    @patch("gantry.gantry.Mill")
    def test_extract_status_returns_unknown_when_empty(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.last_status = ""
        gantry = Gantry(config=self.config)
        self.assertEqual(gantry._extract_status(), "Unknown")

    @patch("gantry.gantry.Mill")
    def test_clear_g92_offsets_sends_g92_1(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.clear_g92_offsets()
        mock_mill.execute_command.assert_called_with("G92.1")

    @patch("gantry.gantry.Mill")
    def test_enforce_work_position_reporting_delegates_to_mill(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.enforce_work_position_reporting()
        mock_mill.enforce_wpos_mode.assert_called_once_with()

    @patch("gantry.gantry.Mill")
    def test_activate_work_coordinate_system_sends_g54(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.activate_work_coordinate_system()
        mock_mill.execute_command.assert_called_with("G54")

    @patch("gantry.gantry.Mill")
    def test_set_work_coordinates_sends_g10_l20(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.set_work_coordinates(400.0, 300.0, 100.0)
        mock_mill.execute_command.assert_called_with("G10 L20 P1 X400 Y300 Z100")

    @patch("gantry.gantry.Mill")
    def test_set_work_coordinates_can_assign_partial_axes(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.set_work_coordinates(x=0.0, y=0.0)
        mock_mill.execute_command.assert_called_with("G10 L20 P1 X0 Y0")

        gantry.set_work_coordinates(z=14.5)
        mock_mill.execute_command.assert_called_with("G10 L20 P1 Z14.5")

    @patch("gantry.gantry.Mill")
    def test_set_serial_timeout_updates_serial_object(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.set_serial_timeout(0.5)
        mock_mill.set_read_timeout.assert_called_once_with(0.5)

    @patch("gantry.gantry.Mill")
    def test_connected_port_comes_from_low_level_driver(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.connected_port.return_value = "/dev/tty.usbserial-130"
        gantry = Gantry(config=self.config)
        self.assertEqual(gantry.connected_port(), "/dev/tty.usbserial-130")

    @patch("gantry.gantry.Mill")
    def test_soft_limits_enabled_reads_setting_semantically(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.read_grbl_settings.return_value = {"$20": "1"}
        gantry = Gantry(config=self.config)
        self.assertTrue(gantry.soft_limits_enabled())

    @patch("gantry.gantry.Mill")
    def test_set_soft_limits_enabled_delegates_to_grbl_setting(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        gantry = Gantry(config=self.config)
        gantry.set_soft_limits_enabled(False)
        mock_mill.set_grbl_setting.assert_called_once_with("20", "0")

    @patch("gantry.gantry.Mill")
    def test_configure_soft_limits_writes_and_verifies_settings(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.read_grbl_settings.return_value = {
            "$20": "1",
            "$22": "1",
            "$130": "306.000",
            "$131": "306.000",
            "$132": "113.000",
        }
        gantry = Gantry(config=self.config)
        gantry.configure_soft_limits_from_spans(
            max_travel_x=306.0,
            max_travel_y=306.0,
            max_travel_z=113.0,
        )
        self.assertEqual(
            mock_mill.set_grbl_setting.call_args_list,
            [
                unittest.mock.call("20", "0"),
                unittest.mock.call("130", "306"),
                unittest.mock.call("131", "306"),
                unittest.mock.call("132", "113"),
                unittest.mock.call("22", "1"),
                unittest.mock.call("20", "1"),
            ],
        )

    @patch("gantry.gantry.Mill")
    def test_configure_soft_limits_reenables_soft_limits_on_write_failure(
        self, mock_mill_cls
    ):
        mock_mill = mock_mill_cls.return_value
        mock_mill.set_grbl_setting.side_effect = [
            None,
            CommandExecutionError("write failed"),
            None,
        ]
        gantry = Gantry(config=self.config)

        with self.assertRaises(CommandExecutionError):
            gantry.configure_soft_limits_from_spans(
                max_travel_x=306.0,
                max_travel_y=306.0,
                max_travel_z=113.0,
            )

        self.assertEqual(
            mock_mill.set_grbl_setting.call_args_list,
            [
                unittest.mock.call("20", "0"),
                unittest.mock.call("130", "306"),
                unittest.mock.call("20", "1"),
            ],
        )


class TestGrblSettingsValidation(unittest.TestCase):
    @patch("gantry.gantry.Mill")
    def test_validate_passes_when_settings_match(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.read_grbl_settings.return_value = {
            "$3": "2",
            "$10": "1",
            "$130": "300.000",
            "$131": "200.000",
        }
        gantry = Gantry(
            config={
                "grbl_settings": {
                    "dir_invert_mask": 2,
                    "status_report": 1,
                    "max_travel_x": 300.0,
                    "max_travel_y": 200.0,
                },
            }
        )
        gantry._validate_grbl_settings()

    @patch("gantry.gantry.Mill")
    def test_board_expected_settings_override_gantry_settings(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.read_grbl_settings.return_value = {"$3": "1", "$130": "306.000"}
        gantry = Gantry(
            config={
                "grbl_settings": {
                    "dir_invert_mask": 2,
                    "max_travel_x": 300.0,
                },
            }
        )
        gantry.set_expected_grbl_settings({"$3": 1.0, "$130": 306.0})
        gantry._validate_grbl_settings()

    @patch("gantry.gantry.Mill")
    def test_validate_raises_on_critical_mismatch(self, mock_mill_cls):
        mock_mill = mock_mill_cls.return_value
        mock_mill.read_grbl_settings.return_value = {"$3": "0", "$130": "300.000"}
        gantry = Gantry(config={"grbl_settings": {"dir_invert_mask": 2}})
        with self.assertRaises(MillConnectionError):
            gantry._validate_grbl_settings()

    @patch("gantry.gantry.Mill")
    def test_validate_skipped_when_no_grbl_settings(self, mock_mill_cls):
        gantry = Gantry(config={})
        gantry._validate_grbl_settings()


if __name__ == "__main__":
    unittest.main()
