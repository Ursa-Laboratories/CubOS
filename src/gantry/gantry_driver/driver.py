"""
This module contains the Mill class, which is used to control a GRBL CNC machine.
The Mill class is used by higher-level wrappers to move instruments (pipette, electrode, etc.)
to the specified coordinates.

The Mill class contains methods to connect to the mill, execute commands,
stop the mill, reset the mill, home the mill, get the current status of the mill, get the
gcode mode of the mill, get the gcode parameters of the mill, and get the gcode parser state
of the mill.
"""

# pylint: disable=line-too-long

# standard libraries
import math
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, Union

# third-party libraries
import serial
import serial.tools.list_ports

from .exceptions import (
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)

# local libraries
from .logger import set_up_command_logger, set_up_mill_logger
from .instruments import Coordinates, InstrumentManager

# Formatted strings for the mill commands
MILL_MOVE = "G01 X{} Y{} Z{}"  # Move to specified coordinates at the specified feed rate
MILL_MOVE_Z = "G01 Z{}"  # Move to specified Z coordinate at the specified feed rate
RAPID_MILL_MOVE = "G00 X{} Y{} Z{}"  # Move to specified coordinates at the maximum feed rate

# Constants
DEFAULT_FEED_RATE = 2000
HOMING_FEED_RATE = 5000
HOMING_TIMEOUT = 90

# Compile regex patterns for extracting coordinates from the mill status
wpos_pattern = re.compile(r"WPos:([\d.-]+),([\d.-]+),([\d.-]+)")
mpos_pattern = re.compile(r"MPos:([\d.-]+),([\d.-]+),([\d.-]+)")
wco_pattern = re.compile(r"WCO:([\d.-]+),([\d.-]+),([\d.-]+)")

axis_conf_table = [
    {"setting_value": 0, "reverse_x": 0, "reverse_y": 0, "reverse_z": 0},
    {"setting_value": 1, "reverse_x": 1, "reverse_y": 0, "reverse_z": 0},
    {"setting_value": 2, "reverse_x": 0, "reverse_y": 1, "reverse_z": 0},
    {"setting_value": 3, "reverse_x": 1, "reverse_y": 1, "reverse_z": 0},
    {"setting_value": 4, "reverse_x": 0, "reverse_y": 0, "reverse_z": 1},
    {"setting_value": 5, "reverse_x": 1, "reverse_y": 0, "reverse_z": 1},
    {"setting_value": 6, "reverse_x": 0, "reverse_y": 1, "reverse_z": 1},
    {"setting_value": 7, "reverse_x": 1, "reverse_y": 1, "reverse_z": 1},
]


class Mill:
    """
    Set up the mill connection and pass commands, including special commands.

    Attributes:
        config (dict): The configuration of the mill.
        ser_mill (serial.Serial): The serial connection to the mill.
        homed (bool): True if the mill is homed, False otherwise.
        active_connection (bool): True if the connection to the mill is active, False otherwise.
        instrument_manager (InstrumentManager): The instrument manager for the mill.
        working_volume (Coordinates): The working volume of the mill.
        logger_location (Path): The location of the logger.
        logger (Logger): The logger for the mill.

    Methods:
        change_logging_level(level): Change the logging level.
        homing_sequence(): Home the mill, set the feed rate, and clear the buffers.
        connect_to_mill(port, baudrate, timeout): Connect to the mill.
        check_for_alarm_state(): Check if the mill is in an alarm state.
        read_mill_config(): Read the mill configuration from the mill and set it as an attribute.
        execute_command(command): Execute a command on the mill.
        stop(): Stop the mill.
        reset(): Reset the mill.
        soft_reset(): Soft reset the mill.
        home(timeout): Home the mill.
        current_status(): Get the current status of the mill.
        set_feed_rate(rate): Set the feed rate of the mill.
        clear_buffers(): Clear the input and output buffers of the mill.
        gcode_mode(): Get the gcode mode of the mill.
        gcode_parameters(): Get the gcode parameters of the mill.
        gcode_parser_state(): Get the gcode parser state of the mill.
        grbl_settings(): Get the GRBL settings of the mill.
        set_grbl_setting(setting, value): Set a GRBL setting of the mill.
        current_coordinates(instrument): Get the current coordinates of the mill.
        move_to_position(x, y, z, coordinates, instrument, travel_z): Move the mill to the specified coordinates, optionally via a given XY-travel Z.
        update_offset(instrument, offset_x, offset_y, offset_z): Update the offset in the config file.
    """

    def __init__(self, port: Optional[str] = None):
        self.logger_location = Path(__file__).parent / "logs"
        self.logger = set_up_mill_logger(self.logger_location)
        self.port = port
        self.config = {}
        self._clean_config()
        self.ser_mill: serial.Serial = None

    def _clean_config(self):
        """Strip comments from config values and initialize state."""
        for key, value in self.config.items():
            if isinstance(value, str) and "(" in value:
                self.config[key] = value.split("(", 1)[0].strip()
        self.homed = False
        self.auto_home = True
        self.active_connection = False
        self.instrument_manager: InstrumentManager = InstrumentManager()
        self.working_volume: Coordinates = self.read_working_volume()
        self.command_logger = set_up_command_logger(self.logger_location)
        self.interactive_mode = False
        self._wco: Optional[Coordinates] = None
        self.last_status: str = ""

    def read_working_volume(self):
        """Checks the mill config for soft limits to be enabled, and then if so check the x, y, and z max travel limits"""
        working_volume: Coordinates = Coordinates(0, 0, 0)
        if self.config.get("$20") == "1":
            self.logger.info("Soft limits are enabled in the mill config")
            xmultiplier = -1
            ymultiplier = -1
            zmultiplier = -1
            working_volume.x = float(self.config["$130"]) * xmultiplier
            working_volume.y = float(self.config["$131"]) * ymultiplier
            working_volume.z = float(self.config["$132"]) * zmultiplier
        else:
            self.logger.warning("Soft limits are not enabled in the mill config")
            self.logger.warning("Using default working volume")
            working_volume = Coordinates(x=-415.0, y=-300.0, z=-200.0)
        return working_volume

    def change_logging_level(self, level):
        """Change the logging level."""
        self.logger.setLevel(level)

    def homing_sequence(self):
        """Home the mill, set the feed rate, and clear the buffers."""
        self.home()
        self.set_feed_rate(5000)
        self.clear_buffers()

    def locate_mill_over_serial(self, port: Optional[str] = None) -> Tuple[serial.Serial, str]:
        """
        Locate the mill over serial.

        Start with the port provided and attempt to connect and then query for the mill settings ($$) to verify the connection.
        If the response does not begin with a $, scan for connected devices and attempt to connect to each one until a valid response is received.
        """
        ser_mill = serial.Serial()
        baudrates = [115200, 9600]
        timeout = 2

        priority_port = port

        ports = []
        if priority_port:
            ports.append(priority_port)

        for p in self._get_available_ports():
             if p.device != priority_port:
                 ports.append(p.device)

        if not ports:
            self.logger.error("No serial ports found to connect to.")
            raise MillConnectionError("No serial ports found. Checked ttyUSB and usbmodem.")

        found = False
        found_on = None
        max_scan_attempts = 3
        scan_attempt = 0
        while not found:
            scan_attempt += 1
            if scan_attempt > max_scan_attempts:
                raise MillConnectionError(
                    f"Could not find GRBL device after {max_scan_attempts} scan attempts"
                )
            for port in ports:
                if not port:
                    continue

                for baudrate in baudrates:
                    try:
                        self.logger.info("Attempting connection to port: %s at %s baud", port, baudrate)
                        ser_mill = serial.Serial(
                            port=port,
                            baudrate=baudrate,
                            timeout=timeout,
                        )

                        if self._verify_connection(ser_mill):
                             self.logger.info(f"Connected successfully to {port} at {baudrate}")
                             found = True
                             found_on = port
                             break
                        else:
                             self.logger.warning(f"No valid GRBL response from {port} at {baudrate}")
                             ser_mill.close()

                    except Exception as e:
                        self.logger.error(f"Error checking {port} at {baudrate}: {e}")
                        if ser_mill.is_open:
                            ser_mill.close()

                if found:
                    break

        self._cache_port(found_on)

        return ser_mill, found_on

    def _get_available_ports(self):
        """List all available serial ports."""
        if os.name == "posix":
            ports = list(serial.tools.list_ports.grep("ttyUSB|usbmodem|usbserial"))
        elif os.name == "nt":
            ports = list(serial.tools.list_ports.grep("COM"))
        else:
            raise OSError("Unsupported OS")
        return ports

    def _verify_connection(self, ser_mill: serial.Serial) -> bool:
        """Verify that the connected device is a GRBL mill."""
        ser_mill.flushInput()
        ser_mill.flushOutput()
        time.sleep(0.1)

        if not ser_mill.is_open:
            ser_mill.open()
            time.sleep(0.5)

        if not ser_mill.is_open:
             return False

        self.logger.info("Querying the mill for status")

        # Wake the controller without forcing a soft reset. Ctrl-X clears
        # transient state, but on machines with homing lock enabled it also
        # drops GRBL back into Alarm until the operator homes again.
        ser_mill.write(b"\r\n")
        time.sleep(0.1)
        ser_mill.flushInput()

        ser_mill.write(b"?")
        time.sleep(0.1)

        ser_mill.write(b"$$\n")
        time.sleep(0.2)

        statuses = ser_mill.readlines()
        self.logger.info(f"Raw response: {statuses}")

        for line in statuses:
            decoded = line.decode(errors='ignore').rstrip()
            if "Grbl" in decoded or "ok" in decoded or "error" in decoded or "Idle" in decoded:
                return True
        return False

    def _cache_port(self, port: str):
         """Cache the port to a file for future connections."""
         with open(Path(__file__).parent / "mill_port.txt", "w") as file:
            file.write(port)

    def connect_to_mill(
        self,
        port: Optional[str] = None,
        baudrate=115200,
        timeout=3,
    ) -> serial.Serial:
        """Connect to the mill."""
        try:
            ser_mill, port_name = self.locate_mill_over_serial(port)

            if ser_mill and ser_mill.is_open:
                self.logger.info("Reusing open serial connection from detection")
                self.ser_mill = ser_mill
            else:
                self.logger.info("Opening new serial connection to mill...")
                self.ser_mill = serial.Serial(
                    port=port_name,
                    baudrate=baudrate,
                    timeout=timeout,
                )
                time.sleep(2)

            if not self.ser_mill.is_open:
                self.ser_mill.open()
                time.sleep(2)

            if self.ser_mill.is_open:
                self.logger.info("Serial connection to mill opened successfully")
                self.active_connection = True
            else:
                self.logger.error("Serial connection to mill failed to open")
                raise MillConnectionError("Error opening serial connection to mill")

            self.logger.info("Mill connected: %s", self.ser_mill.is_open)

        except Exception as exep:
            self.logger.error("Error connecting to the mill: %s", str(exep))
            raise MillConnectionError("Error connecting to the mill") from exep

        # Quick alarm check before sending any commands — GRBL rejects
        # everything except $X and $H while in alarm state.
        self.ser_mill.write(b"?")
        time.sleep(0.2)
        initial_status = self.read()
        if initial_status and "alarm" in initial_status.lower():
            self.logger.warning(
                "Mill is in alarm state — skipping config/setup. "
                "Unlock ($X) or home ($H) to clear. Status: %s",
                initial_status,
            )
            return self.ser_mill

        self.read_mill_config()
        self.read_working_volume()

        self.clear_buffers()
        if initial_status:
            self._enforce_wpos_mode()
        else:
            self.logger.warning(
                "No initial GRBL status response; skipping WPos enforcement during connect"
            )
        self.set_feed_rate(DEFAULT_FEED_RATE)
        if initial_status:
            self._seed_wco()
        return self.ser_mill

    def check_for_alarm_state(self):
        """Check if the mill is in an alarm state."""
        self.ser_mill.write(b"?")
        time.sleep(0.1)
        status = self.read()
        self.logger.debug("Status: %s", status)
        if not status:
            self.logger.warning("No response to status query, retrying")
            status = self.current_status()
            self.logger.debug("Status: %s", status)
            if not status:
                self.logger.error("Failed to get status from the mill")
                raise MillConnectionError("Failed to get status from the mill")
        if "alarm" in status.lower():
            self.logger.warning("Mill is in alarm state. Requesting user input")
            reset_alarm = "y"
            if reset_alarm[0].lower() == "y":
                self.logger.info("Resetting the mill")
                self.reset()
            else:
                self.logger.error(
                    "Mill is in alarm state, user chose not to reset the mill"
                )
                raise MillConnectionError("Mill is in alarm state")
        if "error" in status.lower():
            self.logger.error("Error in status: %s", status)
            raise MillConnectionError(f"Error in status: {status}")

    def __enter__(self):
        """Enter the context manager."""
        self.connect_to_mill(port=self.port)
        self.set_feed_rate(5000)

        if not self.homed and getattr(self, "auto_home", True):
            self.homing_sequence()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the context manager."""
        self.disconnect()
        self.logger.info("Exiting the mill context manager")

    def disconnect(self):
        """Close the serial connection to the mill."""
        self.logger.info("Disconnecting from the mill")

        if self.ser_mill:
            self.ser_mill.close()
            time.sleep(2)
            if self.ser_mill.is_open:
                self.logger.error("Failed to close the serial connection to the mill")
                raise MillConnectionError("Error closing serial connection to mill")
            else:
                self.logger.info("Serial connection to mill closed successfully")
                self.active_connection = False
                self.ser_mill = None
        else:
             self.logger.info("Serial connection was already closed or never opened.")
        return

    def read_mill_config(self):
        """Read the live mill config from the connected controller."""
        if self.ser_mill is None or not self.ser_mill.is_open:
            self.logger.error("Serial connection to mill is not open")
            raise MillConnectionError("Serial connection to mill is not open")

        self.logger.info("Reading mill config")
        mill_config = self.grbl_settings()
        self.config = mill_config
        self.logger.debug("Mill config: %s", mill_config)
        return mill_config

    def _parse_grbl_settings_response(self, response_lines: List[str]) -> dict:
        """Parse a GRBL $$ response into a settings dictionary."""
        settings_dict = {}
        self.logger.info("Parsing settings from: %s", response_lines)
        for setting in response_lines:
            if not setting:
                continue
            if setting.startswith("[MSG") or "Grbl" in setting:
                continue
            if "=" not in setting:
                self.logger.warning("Skipping non-setting line: %s", setting)
                continue
            try:
                key, value = setting.split("=", 1)
                if "(" in value:
                    value = value.split("(", 1)[0]
                settings_dict[key.strip()] = value.strip()
            except ValueError:
                self.logger.error("Failed to parse setting line: %s", setting)
                continue
        return settings_dict

    def execute_command(self, command: str, suppress_errors: bool = False):
        """Encodes and sends commands to the mill and returns the response."""
        try:
            self.logger.debug("Command sent: %s", command)
            self.command_logger.debug("%s", command)
            command_bytes = str(command).encode(encoding="ascii")
            self.ser_mill.write(command_bytes + b"\n")

            if command == "$$":
                full_mill_response = [
                    self.ser_mill.readline().decode(encoding="ascii").rstrip()
                ]
                while full_mill_response[-1] != "ok":
                    full_mill_response.append(
                        self.ser_mill.readline().decode(encoding="ascii").rstrip()
                    )
                full_mill_response = full_mill_response[:-1]
                self.logger.debug("Returned %s", full_mill_response)
                return self._parse_grbl_settings_response(full_mill_response)

            mill_response = self.read().lower()
            if not command.startswith("$"):
                mill_response = self.__wait_for_completion(mill_response, suppress_errors=suppress_errors)
                self.logger.debug("Returned %s", mill_response)
            else:
                self.logger.debug("Returned %s", mill_response)

            if re.search(r"(error|alarm)", mill_response):
                if re.search(r"error:22", mill_response):
                    self.logger.error("Error in status: %s", mill_response)
                    self.set_feed_rate(DEFAULT_FEED_RATE)
                    mill_response = self.execute_command(command, suppress_errors=suppress_errors)
                else:
                    if not suppress_errors:
                        self.logger.error(
                            "current_status: Error in status: %s", mill_response
                        )
                    raise StatusReturnError(f"Error in status: {mill_response}")

        except Exception as exep:
            if not suppress_errors:
                self.logger.error("Error executing command %s: %s", command, str(exep))
            raise CommandExecutionError(
                f"Error executing command {command}: {str(exep)}"
            ) from exep

        return mill_response

    def stop(self):
        """Stop the mill."""
        self.execute_command("!")

    def jog(self, x: float = 0, y: float = 0, z: float = 0,
            feed_rate: float = DEFAULT_FEED_RATE) -> None:
        """Send a GRBL jog command ($J=) for immediate, cancellable movement.

        Unlike G-code moves, jog commands are non-blocking and can be
        cancelled instantly with a jog-cancel (0x85).

        Args:
            x: Relative X distance.
            y: Relative Y distance.
            z: Relative Z distance.
            feed_rate: Feed rate in mm/min.
        """
        if not self.ser_mill:
            raise MillConnectionError("Serial connection not available")
        parts = []
        if x != 0:
            parts.append(f"X{x:.3f}")
        if y != 0:
            parts.append(f"Y{y:.3f}")
        if z != 0:
            parts.append(f"Z{z:.3f}")
        if not parts:
            return
        cmd = f"$J=G91 {' '.join(parts)} F{feed_rate}"
        self.logger.debug("Jog command: %s", cmd)
        self.ser_mill.write((cmd + "\n").encode("ascii"))
        response = self.read().lower()
        if (
            "error" in response
            or "alarm" in response
            or "check limits" in response
        ):
            # error:8 = "not idle" (planner buffer full) — safe to ignore
            if "error:8" in response:
                self.logger.debug("Jog buffer full, skipping")
                return
            self.logger.error("Jog error: %s", response)
            raise CommandExecutionError(f"Jog failed: {response}")

    def jog_cancel(self) -> None:
        """Cancel any in-progress jog motion immediately."""
        if not self.ser_mill:
            raise MillConnectionError("Serial connection not available")
        self.ser_mill.write(b"\x85")

    def reset(self):
        """Unlock the mill by sending $X directly over serial."""
        if not self.ser_mill:
            raise MillConnectionError("Serial connection not available")
        self.logger.info("Sending unlock ($X)")
        self.ser_mill.write(b"$X\n")
        time.sleep(0.5)
        # Drain and check response
        response_lines = []
        while self.ser_mill.in_waiting:
            line = self.ser_mill.readline().decode("ascii", errors="replace").strip()
            self.logger.debug("Unlock response: %s", line)
            response_lines.append(line)
        for line in response_lines:
            if "error" in line.lower():
                raise CommandExecutionError(f"Unlock ($X) failed: {line}")

    def soft_reset(self):
        """Soft reset the mill (GRBL Ctrl-X / 0x18)."""
        if not self.ser_mill:
            raise MillConnectionError("Serial connection not available")
        self.logger.info("Sending soft reset (0x18)")
        self.ser_mill.write(b"\x18")
        time.sleep(1.0)
        while self.ser_mill.in_waiting:
            line = self.ser_mill.readline().decode("ascii", errors="replace").strip()
            self.logger.debug("Soft reset response: %s", line)

    def soft_reset_and_unlock(self):
        """Soft reset followed by unlock — single serial sequence."""
        self.soft_reset()
        self.reset()

    def home(self, timeout=HOMING_TIMEOUT):
        """Home the mill with a timeout."""
        self.execute_command("$H")
        time.sleep(1)
        start_time = time.time()
        last_status_error = None

        while True:
            if time.time() - start_time > timeout:
                self.logger.warning("Homing timed out")
                if last_status_error is not None:
                    raise StatusReturnError(
                        f"Homing timed out after {timeout} seconds; "
                        f"last status error: {last_status_error}"
                    ) from last_status_error
                raise StatusReturnError(f"Homing timed out after {timeout} seconds")

            try:
                status = self.current_status()
            except StatusReturnError as exc:
                last_status_error = exc
                self.logger.warning("No valid status during homing; retrying: %s", exc)
                time.sleep(0.5)
                continue

            if "Idle" in status:
                self.logger.info("Homing completed")
                self.homed = True
                break

            if "Alarm" in status or "alarm" in status:
                self.logger.warning("Homing failed, trying again...")
                self.execute_command("$H")

            time.sleep(0.5)

    def __wait_for_completion(self, incoming_status, suppress_errors: bool = False, timeout=5):
        """Wait for the mill to complete the previous command."""
        status = incoming_status
        start_time = time.time()
        while "Idle" not in status:
            if "<Run" in status:
                start_time = time.time()
            if "error" in status:
                if not suppress_errors:
                    self.logger.error("Error in status: %s", status)
                raise StatusReturnError(f"Error in status: {status}")
            if "alarm" in status:
                if not suppress_errors:
                    self.logger.error("Alarm in status: %s", status)
                raise StatusReturnError(f"Alarm in status: {status}")
            if time.time() - start_time > timeout:
                self.logger.warning("Command execution timed out")
                raise StatusReturnError(
                    f"Command execution timed out after {timeout} seconds: {status}"
                )
            status = self.current_status()
        return status

    def current_status(self) -> str:
        """Get the current status of the mill."""
        attempt_limit = 5
        status = self.read()

        while status in ["", "ok"] and attempt_limit > 0:
            self.ser_mill.write(b"?")
            time.sleep(0.05)
            status = self.read()
            attempt_limit -= 1

        if not status:
            raw_lines = self.ser_mill.readlines()
            lines = [item.decode().rstrip() for item in raw_lines]
            if not lines:
                self.logger.error("Failed to get status from the mill")
                if self.interactive_mode:
                    print("Failed to get status from the mill")
                    return ""
                raise StatusReturnError("Failed to get status from the mill")
            # Find the first status line (<...>) or join all lines
            status = next((l for l in lines if l.startswith("<")), "; ".join(lines))
            if any(re.search(r"\b(error|alarm)\b", item.lower()) for item in lines):
                self.logger.error("Error in status: %s", status)
                self.last_status = status
                if self.interactive_mode:
                    print(f"Error in status: {status}")
                    return ""
                raise StatusReturnError(f"Error in status: {status}")
        self.last_status = status
        return status

    def write(self, command: str):
        """Write a command to the mill."""
        command = command.upper()
        if command != "?":
            command += "\n"

        self.ser_mill.write(command.encode(encoding="ascii"))

    def read(self):
        msg = self.ser_mill.read(1)
        if msg == b"":
            return ""
        msg += self.ser_mill.read_all()
        msg = msg.decode(encoding="ascii")
        return msg

    def txrx(self, command: str) -> str:
        """Write a command to the mill and read the response."""
        self.write(command)
        time.sleep(0.2)
        return self.read()

    def set_feed_rate(self, rate):
        """Set the feed rate."""
        self.execute_command(f"F{rate}")

    def clear_buffers(self):
        """Clear input and output buffers."""
        self.ser_mill.flush()
        self.ser_mill.read_all()

    def gcode_mode(self):
        """Ask the mill for its gcode mode."""
        self.execute_command("$C")

    def gcode_parameters(self):
        """Ask the mill for its gcode parameters."""
        return self.execute_command("$#")

    def gcode_parser_state(self):
        """Ask the mill for its gcode parser state."""
        return self.execute_command("$G")

    def grbl_settings(self) -> dict:
        """Return live GRBL settings from the connected controller."""
        if self.ser_mill is None or not self.ser_mill.is_open:
            raise MillConnectionError("Serial connection to mill is not open")
        settings = self.execute_command("$$")
        self.config = settings
        return settings

    def set_grbl_setting(self, setting: str, value: str):
        """Set a grbl setting."""
        command = f"${setting}={value}"
        return self.execute_command(command)

    def _enforce_wpos_mode(self):
        """Ensure GRBL reports WPos in status reports ($10=0) and uses absolute positioning (G90)."""
        current = self.config.get("$10", "1")
        if current != "0":
            self.logger.info("Setting $10=0 (WPos status reporting)")
            self.execute_command("$10=0")
            self.config["$10"] = "0"
        try:
            self.execute_command("G90")
        except CommandExecutionError:
            self.logger.warning(
                "Could not verify G90 during connect; continuing with existing parser state"
            )
        self.logger.info("WPos mode and absolute positioning enforced")

    def _seed_wco(self):
        """Poll GRBL status until WCO is reported, then cache it.

        GRBL includes WCO periodically in status reports. We query
        repeatedly so that we have the offset cached for any MPos→WPos
        conversion that might be needed.
        """
        for _ in range(15):
            self.ser_mill.write(b"?")
            time.sleep(0.15)
            status = self.read()
            match = wco_pattern.search(status)
            if match:
                self._wco = Coordinates(
                    float(match.group(1)),
                    float(match.group(2)),
                    float(match.group(3)),
                )
                self.logger.info("WCO cached: %s", self._wco)
                return
        self.logger.warning("Could not obtain WCO from GRBL status reports")

    def _query_work_coordinate_offset(self) -> Coordinates:
        """Return the cached Work Coordinate Offset (WCO).

        WCO is the offset between machine position and work position:
            MPos = WPos + WCO
        """
        if self._wco is None:
            self._seed_wco()
        if self._wco is None:
            self.logger.warning("WCO unavailable, returning zero offset")
            return Coordinates(0, 0, 0)
        return self._wco

    def machine_coordinates(self) -> Coordinates:
        """Return the current machine position (MPos = WPos + WCO)."""
        wpos = self.current_coordinates()
        wco = self._query_work_coordinate_offset()
        return Coordinates(
            round(wpos.x + wco.x, 3),
            round(wpos.y + wco.y, 3),
            round(wpos.z + wco.z, 3),
        )

    def is_connected(self) -> bool:
        """Check if the serial connection is open."""
        return bool(self.ser_mill and self.ser_mill.is_open)

    def query_raw_status(self) -> str:
        """Send GRBL '?' and return the raw status string (e.g. '<Idle|WPos:...>')."""
        if not self.is_connected():
            return ""
        try:
            self.ser_mill.write(b"?")
            time.sleep(0.1)
            for _ in range(5):
                raw = self.read()
                if isinstance(raw, str) and "<" in raw:
                    return raw
                time.sleep(0.05)
            return str(raw) if raw else ""
        except Exception:
            return ""

    def current_coordinates(
        self, instrument: Optional[str] = None, instrument_only: bool = True
    ) -> Union[Coordinates, Tuple[Coordinates, Coordinates]]:
        """
        Get the current coordinates of the mill.

        Args:
            instrument (str): The instrument for which to get the offset coordinates.
            instrument_only (bool): If True, return only the instrument head position.

        Returns:
            Coordinates or Tuple[Coordinates, Coordinates]: mill_center [x,y,z] or (mill_center, instrument_head).
        """
        self.ser_mill.write(b"?")
        time.sleep(0.05)
        status = self.read()
        attempts = 0
        while (not status or status[0] != "<") and attempts < 3:
            if "alarm" in status.lower() or "error" in status.lower():
                self.logger.error("Error in status: %s", status)
                self.last_status = status
                raise StatusReturnError(f"Error in status: {status}")
            if "ok" in status.lower():
                self.logger.debug("OK in status: %s", status)
            status = self.read()
            attempts += 1

        self.last_status = status
        status_mode = int(self.config["$10"])

        if int(status_mode) not in [0, 1, 2, 3]:
            self.logger.error("Invalid status mode")
            raise ValueError("Invalid status mode")

        max_attempts = 3
        pattern = wpos_pattern if status_mode in [0, 2] else mpos_pattern
        coord_type = "WPos" if status_mode in [0, 2] else "MPos"

        # Update cached WCO whenever GRBL includes it in the status
        wco_match = wco_pattern.search(status)
        if wco_match:
            self._wco = Coordinates(
                float(wco_match.group(1)),
                float(wco_match.group(2)),
                float(wco_match.group(3)),
            )

        for i in range(max_attempts):
            match = pattern.search(status)
            if match:
                x_coord = round(float(match.group(1)), 3)
                y_coord = round(float(match.group(2)), 3)
                z_coord = round(float(match.group(3)), 3)
                if coord_type == "MPos":
                    if self._wco is None:
                        self._seed_wco()
                    if self._wco is not None:
                        x_coord = round(x_coord - self._wco.x, 3)
                        y_coord = round(y_coord - self._wco.y, 3)
                        z_coord = round(z_coord - self._wco.z, 3)
                    else:
                        self.logger.warning(
                            "MPos reported but WCO unavailable; returning raw MPos"
                        )
                self.logger.info(
                    "WPos coordinates: X = %s, Y = %s, Z = %s",
                    x_coord,
                    y_coord,
                    z_coord,
                )
                break
            else:
                self.logger.warning(
                    "%s coordinates not found in status: %r. Retrying query...",
                    coord_type,
                    status,
                )
                if i == max_attempts - 1:
                    self.logger.error(
                        "Error occurred while getting %s coordinates", coord_type
                    )
                    raise LocationNotFound
                # Re-query status for next attempt
                time.sleep(0.2)
                self.ser_mill.write(b"?")
                time.sleep(0.2)
                status = self.read()
                retry_attempts = 0
                while (not status or status[0] != "<") and retry_attempts < 3:
                    status = self.read()
                    retry_attempts += 1

        mill_center = Coordinates(x_coord, y_coord, z_coord)
        # Adjust coordinates based on the instrument to report where it currently is
        if instrument:
            try:
                offsets = self.instrument_manager.get_offset(instrument)
                # NOTE: subtraction because we are reporting where the instrument head is
                instrument_head = Coordinates(
                    x_coord - offsets.x,
                    y_coord - offsets.y,
                    z_coord - offsets.z,
                )

            except Exception as exception:
                raise ValueError("Invalid instrument") from exception

            if instrument_only:
                return instrument_head
            else:
                return mill_center, instrument_head
        else:
            return mill_center

    def move_to_position(
        self,
        x_coordinate: float = 0.00,
        y_coordinate: float = 0.00,
        z_coordinate: float = 0.00,
        coordinates: Coordinates = None,
        instrument: str = "center",
        travel_z: Optional[float] = None,
    ) -> None:
        """
        Move the mill to the specified coordinates.

        When ``travel_z`` is provided, XY travel happens at that Z rather
        than whatever Z the tip is currently at. The sequence becomes:
        lift/lower to ``travel_z`` at current XY, XY travel at ``travel_z``,
        then descend/ascend to the target Z. This lets callers (Board,
        protocol commands) own their own "safe approach" height instead of
        the mill baking in a machine-wide retract.

        When ``travel_z`` is None, the mill issues a direct axis-by-axis
        move (X, then Y, then Z) — no Z detour, no diagonal interpolation.

        Args:
            x_coordinate (float): X coordinate.
            y_coordinate (float): Y coordinate.
            z_coordinate (float): Z coordinate.
            coordinates (Coordinates): Target coordinates object (overrides x/y/z params).
            instrument (str): Instrument to move (default: "center").
            travel_z (float): Machine-space Z to hold during XY travel.
        """
        goto = (
            Coordinates(x=x_coordinate, y=y_coordinate, z=z_coordinate)
            if not coordinates
            else coordinates
        )
        self._validate_target_coordinates(goto)
        if travel_z is not None:
            self._validate_finite_coordinate(travel_z, "travel Z")
        offsets = self.instrument_manager.get_offset(instrument)
        current_coordinates = self.current_coordinates()

        target_coordinates = self._calculate_target_coordinates(
            goto, current_coordinates, offsets
        )

        if self._is_already_at_target(target_coordinates, current_coordinates):
            self.logger.debug(
                "%s is already at the target coordinates of [%s, %s, %s]",
                instrument,
                x_coordinate,
                y_coordinate,
                z_coordinate,
            )
            return

        self._log_target_coordinates(target_coordinates)
        self._validate_target_coordinates(target_coordinates)

        if travel_z is None:
            commands = self._generate_movement_commands(
                current_coordinates, target_coordinates
            )
        else:
            gantry_travel_z = travel_z + offsets.z
            commands = self._generate_transit_commands(
                current_coordinates, target_coordinates, gantry_travel_z
            )
        for cmd in commands:
            self.execute_command(cmd)

    def update_offset(self, instrument, offset_x, offset_y, offset_z):
        """Update the offset for an instrument."""
        current_offset = self.instrument_manager.get_offset(instrument)
        new_offset = Coordinates(
            current_offset.x + offset_x,
            current_offset.y + offset_y,
            current_offset.z + offset_z,
        )

        self.instrument_manager.update_instrument(instrument, new_offset)

    def _is_already_at_target(
        self, goto: Coordinates, current_coordinates: Coordinates
    ):
        """Check if the mill is already at the target coordinates."""
        return (goto.x, goto.y) == (
            current_coordinates.x,
            current_coordinates.y,
        ) and goto.z == current_coordinates.z

    def _calculate_target_coordinates(
        self, goto: Coordinates, current_coordinates: Coordinates, offsets: Coordinates
    ):
        """
        Calculate the target coordinates for the mill, applying instrument offsets.

        Args:
            goto (Coordinates): The target coordinates.
            current_coordinates (Coordinates): The current coordinates of the mill center.
            offsets (Coordinates): The offsets for the instrument.
        """
        return Coordinates(
            x=goto.x + offsets.x,
            y=goto.y + offsets.y,
            z=goto.z + offsets.z,
        )

    def _log_target_coordinates(self, target_coordinates: Coordinates):
        self.logger.debug(
            "Target coordinates: [%s, %s, %s]",
            target_coordinates.x,
            target_coordinates.y,
            target_coordinates.z,
        )

    def _validate_target_coordinates(self, target_coordinates: Coordinates):
        self._validate_finite_coordinate(target_coordinates.x, "target X")
        self._validate_finite_coordinate(target_coordinates.y, "target Y")
        self._validate_finite_coordinate(target_coordinates.z, "target Z")

    @staticmethod
    def _validate_finite_coordinate(value: float, label: str) -> None:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be finite; got {value!r}.") from exc
        if not math.isfinite(numeric_value):
            raise ValueError(f"{label} must be finite; got {value!r}.")

    def _generate_movement_commands(
        self,
        current_coordinates: Coordinates,
        target_coordinates: Coordinates,
    ):
        """Direct move from current to target, axis-by-axis.

        Emits one G-code per changed axis in X-then-Y-then-Z order.
        The mill never commands simultaneous multi-axis (diagonal)
        motion — combining axes in a single G01 would couple their
        motion into a straight interpolation that could graze
        obstacles the caller didn't plan for.
        """
        f = f" F{DEFAULT_FEED_RATE}"
        self._validate_target_coordinates(target_coordinates)
        commands = []
        if target_coordinates.x != current_coordinates.x:
            commands.append(f"G01 X{target_coordinates.x}{f}")
        if target_coordinates.y != current_coordinates.y:
            commands.append(f"G01 Y{target_coordinates.y}{f}")
        if target_coordinates.z != current_coordinates.z:
            commands.append(f"G01 Z{target_coordinates.z}{f}")
        return commands

    def _generate_transit_commands(
        self,
        current_coordinates: Coordinates,
        target_coordinates: Coordinates,
        travel_z: float,
    ):
        """Transit via ``travel_z``, axis-by-axis: lift → X → Y → descend.

        Each step is emitted only when it would produce actual motion,
        so a move already at ``travel_z`` skips the lift, a same-X
        (or same-Y) move skips that axis, and a final Z matching
        ``travel_z`` skips the descent. X and Y always move in
        separate G-codes — no diagonal.
        """
        f = f" F{DEFAULT_FEED_RATE}"
        self._validate_target_coordinates(target_coordinates)
        self._validate_finite_coordinate(travel_z, "travel Z")
        commands = []
        if current_coordinates.z != travel_z:
            commands.append(f"G01 Z{travel_z}{f}")
        if target_coordinates.x != current_coordinates.x:
            commands.append(f"G01 X{target_coordinates.x}{f}")
        if target_coordinates.y != current_coordinates.y:
            commands.append(f"G01 Y{target_coordinates.y}{f}")
        if target_coordinates.z != travel_z:
            commands.append(f"G01 Z{target_coordinates.z}{f}")
        return commands
