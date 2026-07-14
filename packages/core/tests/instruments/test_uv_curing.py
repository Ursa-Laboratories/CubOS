"""Tests for the Excelitas OmniCure S1500 PRO UV curing driver."""

import unittest
from unittest.mock import patch, MagicMock

from cubos.instruments.base_instrument import BaseInstrument, InstrumentError
from cubos.instruments.uv_curing.vendors.excelitas import ExcelitasUVCuring
from cubos.instruments.uv_curing.models import CureResult, UVCuringStatus
from cubos.instruments.uv_curing.exceptions import (
    UVCuringError,
    UVCuringConnectionError,
    UVCuringCommandError,
    UVCuringTimeoutError,
)


class TestExceptionHierarchy(unittest.TestCase):

    def test_base_is_instrument_error(self):
        self.assertTrue(issubclass(UVCuringError, InstrumentError))

    def test_connection_error(self):
        self.assertTrue(issubclass(UVCuringConnectionError, UVCuringError))

    def test_command_error(self):
        self.assertTrue(issubclass(UVCuringCommandError, UVCuringError))

    def test_timeout_error(self):
        self.assertTrue(issubclass(UVCuringTimeoutError, UVCuringError))


class TestCureResult(unittest.TestCase):

    def test_frozen(self):
        r = CureResult(intensity_percent=50.0, exposure_time_s=1.0, timestamp=0.0)
        with self.assertRaises(AttributeError):
            r.intensity_percent = 99.0


class TestUVCuringIsBaseInstrument(unittest.TestCase):

    def test_is_subclass(self):
        self.assertTrue(issubclass(ExcelitasUVCuring, BaseInstrument))


class TestUVCuringOffline(unittest.TestCase):

    def setUp(self):
        self.uv = ExcelitasUVCuring(offline=True, default_intensity=50.0,
                           default_exposure_time=2.0)

    def test_connect_disconnect(self):
        self.uv.connect()
        self.uv.disconnect()

    def test_health_check(self):
        self.assertTrue(self.uv.health_check())

    def test_cure_returns_result(self):
        result = self.uv.cure(intensity=80.0, exposure_time=3.0)
        self.assertIsInstance(result, CureResult)
        self.assertAlmostEqual(result.intensity_percent, 80.0)
        self.assertAlmostEqual(result.exposure_time_s, 3.0)

    def test_cure_uses_defaults(self):
        result = self.uv.cure()
        self.assertAlmostEqual(result.intensity_percent, 50.0)
        self.assertAlmostEqual(result.exposure_time_s, 2.0)

    def test_cure_rejects_zero_intensity(self):
        with self.assertRaises(UVCuringCommandError):
            self.uv.cure(intensity=0)

    def test_cure_rejects_intensity_over_100(self):
        with self.assertRaises(UVCuringCommandError):
            self.uv.cure(intensity=101)

    def test_cure_rejects_zero_exposure(self):
        with self.assertRaises(UVCuringCommandError):
            self.uv.cure(exposure_time=0)

    def test_cure_rejects_exposure_below_tenth_second(self):
        with self.assertRaises(UVCuringCommandError):
            self.uv.cure(exposure_time=0.05)

    def test_measure_is_alias(self):
        result = self.uv.measure(intensity=10.0)
        self.assertIsInstance(result, CureResult)

    def test_get_status(self):
        status = self.uv.get_status()
        self.assertIsInstance(status, UVCuringStatus)
        self.assertTrue(status.is_connected)


class TestUVCuringOnlineGuards(unittest.TestCase):

    def test_health_check_false_without_connect(self):
        uv = ExcelitasUVCuring(offline=False)
        self.assertFalse(uv.health_check())

    def test_send_command_raises_without_connect(self):
        uv = ExcelitasUVCuring(offline=False)
        with self.assertRaises(UVCuringCommandError):
            uv._send_command("CONN")


class TestUVCuringMockedSerial(unittest.TestCase):

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_connect_opens_serial_and_handshakes(self, mock_serial_cls):
        mock_ser = mock_serial_cls.return_value
        mock_ser.readline.return_value = b"READY\r\n"
        mock_ser.is_open = True
        uv = ExcelitasUVCuring(port="/dev/ttyACM0", offline=False)
        uv.connect()
        mock_serial_cls.assert_called_once()
        # CONN was sent during handshake
        mock_ser.write.assert_called()

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_connect_raises_on_serial_error(self, mock_serial_cls):
        mock_serial_cls.side_effect = serial.SerialException("no port")
        uv = ExcelitasUVCuring(port="/dev/fake", offline=False)
        with self.assertRaises(UVCuringConnectionError):
            uv.connect()

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_send_command_format(self, mock_serial_cls):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.return_value = b"READY\r\n"
        uv = ExcelitasUVCuring(offline=False)
        uv.connect()
        mock_ser.reset_mock()
        mock_ser.readline.return_value = b"OK\r\n"
        uv._send_command("SIL50")
        mock_ser.write.assert_called_with(b"SIL50XX\r")

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_send_command_timeout(self, mock_serial_cls):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.return_value = b"READY\r\n"
        uv = ExcelitasUVCuring(offline=False)
        uv.connect()
        mock_ser.readline.return_value = b""
        with self.assertRaises(UVCuringTimeoutError):
            uv._send_command("SIL50")

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_disconnect_closes_serial(self, mock_serial_cls):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.return_value = b"READY\r\n"
        uv = ExcelitasUVCuring(offline=False)
        uv.connect()
        uv.disconnect()
        mock_ser.close.assert_called_once()

    @patch('cubos.instruments.uv_curing.vendors.excelitas.time.sleep')
    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_cure_rounds_exposure_to_tenths(self, mock_serial_cls, mock_sleep):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.side_effect = [
            b"READY\r\n",
            b"OK\r\n",
            b"OK\r\n",
            b"OK\r\n",
        ]
        uv = ExcelitasUVCuring(offline=False)
        uv.connect()
        mock_ser.reset_mock()

        uv.cure(intensity=50, exposure_time=1.99)

        written = [call[0][0] for call in mock_ser.write.call_args_list]
        self.assertIn(b"STM20XX\r", written)

    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_failed_handshake_closes_port_and_health_check_false(self, mock_serial_cls):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.return_value = b"NOPE\r\n"
        uv = ExcelitasUVCuring(offline=False)

        with self.assertRaises(UVCuringConnectionError):
            uv.connect()

        mock_ser.close.assert_called_once()
        self.assertFalse(uv.health_check())

    @patch('cubos.instruments.uv_curing.vendors.excelitas.time.sleep')
    @patch('cubos.instruments.uv_curing.vendors.excelitas.serial.Serial')
    def test_sil_nack_raises_command_error(self, mock_serial_cls, mock_sleep):
        mock_ser = mock_serial_cls.return_value
        mock_ser.is_open = True
        mock_ser.readline.side_effect = [
            b"READY\r\n",
            b"NACK\r\n",
        ]
        uv = ExcelitasUVCuring(offline=False)
        uv.connect()

        with self.assertRaises(UVCuringCommandError):
            uv.cure(intensity=50, exposure_time=1.0)


import serial  # needed for SerialException in test
