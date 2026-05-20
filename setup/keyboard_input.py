"""Helper module for reading raw keypresses without requiring Enter.

Cross-platform: uses tty/termios on Unix, msvcrt on Windows.
"""

from collections import deque
import sys
import time

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt
else:
    import select
    import tty
    import termios

_ARROW_MAP_UNIX = {
    "[A": "UP",
    "[B": "DOWN",
    "[C": "RIGHT",
    "[D": "LEFT",
}

# Windows arrow keys: msvcrt returns b'\xe0' or b'\x00' followed by a scan code
_ARROW_MAP_WINDOWS = {
    b"H": "UP",
    b"P": "DOWN",
    b"M": "RIGHT",
    b"K": "LEFT",
}

_REPEAT_BATCH_TIMEOUT_S = 0.03
_PENDING_KEYS = deque()


def _read_one_or_pending(read_one):
    if _PENDING_KEYS:
        return _PENDING_KEYS.popleft()
    return read_one()


def _read_keypress_batch_impl(read_one, key_available, repeat_timeout_s):
    """Batch same-key repeats without discarding the next different key."""
    key = _read_one_or_pending(read_one)
    count = 1

    while key_available(repeat_timeout_s):
        next_key = _read_one_or_pending(read_one)
        if next_key == key:
            count += 1
        else:
            _PENDING_KEYS.appendleft(next_key)
            break

    return key, count


# ── Unix implementation ───────────────────────────────────────────────────────

def _unix_read_one_key():
    """Read a single key. Must already be in raw mode."""
    ch = sys.stdin.read(1)
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x1b":
        seq = sys.stdin.read(2)
        return _ARROW_MAP_UNIX.get(seq, ch)
    return ch.upper()


def _unix_flush_stdin():
    """Discard any buffered stdin without blocking."""
    _PENDING_KEYS.clear()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _unix_read_keypress_batch():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        def key_available(timeout_s):
            return bool(_PENDING_KEYS) or bool(select.select([sys.stdin], [], [], timeout_s)[0])

        return _read_keypress_batch_impl(
            _unix_read_one_key,
            key_available,
            _REPEAT_BATCH_TIMEOUT_S,
        )
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ── Windows implementation ────────────────────────────────────────────────────

def _windows_read_one_key():
    """Read a single key using msvcrt."""
    ch = msvcrt.getch()
    if ch == b"\x03":
        raise KeyboardInterrupt
    if ch in (b"\xe0", b"\x00"):
        scan = msvcrt.getch()
        return _ARROW_MAP_WINDOWS.get(scan, "")
    return ch.decode("ascii", errors="ignore").upper()


def _windows_flush_stdin():
    """Discard any buffered stdin without blocking."""
    _PENDING_KEYS.clear()
    while msvcrt.kbhit():
        msvcrt.getch()


def _windows_read_keypress_batch():
    def key_available(timeout_s):
        if _PENDING_KEYS:
            return True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return True
            time.sleep(0.005)
        return False

    return _read_keypress_batch_impl(
        _windows_read_one_key,
        key_available,
        _REPEAT_BATCH_TIMEOUT_S,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def read_keypress() -> str:
    """Read a single keypress and return a normalized string."""
    if _IS_WINDOWS:
        return _windows_read_one_key()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return _unix_read_one_key()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def read_keypress_batch() -> tuple:
    """Read a keypress, then drain any buffered repeats of the same key.

    When a key is held down, the terminal generates repeated key events.
    This function consumes all buffered repeats and returns the key plus
    a count, so the caller can send a single larger move.

    Returns:
        (key_name, count) where count >= 1.
    """
    if _IS_WINDOWS:
        return _windows_read_keypress_batch()
    return _unix_read_keypress_batch()


def flush_stdin() -> None:
    """Discard any buffered stdin without blocking.

    Call this after a blocking operation (e.g. gantry.move_to) to throw
    away keypresses that accumulated while the operation was running.
    """
    if _IS_WINDOWS:
        _windows_flush_stdin()
    else:
        _unix_flush_stdin()
