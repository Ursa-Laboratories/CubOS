"""Tests for raw keyboard helpers."""

from __future__ import annotations

import pytest

from setup import keyboard_input


class _FakeStdin:
    def __init__(self, chars: str):
        self._chars = iter(chars)

    def read(self, _count: int) -> str:
        return next(self._chars)


def test_unix_raw_ctrl_c_raises_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(keyboard_input.sys, "stdin", _FakeStdin("\x03"))

    with pytest.raises(KeyboardInterrupt):
        keyboard_input._unix_read_one_key()


def test_keypress_batch_counts_same_repeats():
    keyboard_input._PENDING_KEYS.clear()
    keys = iter(["RIGHT", "RIGHT", "RIGHT"])
    availability = iter([True, True, False])

    key, count = keyboard_input._read_keypress_batch_impl(
        lambda: next(keys),
        lambda _timeout_s: next(availability),
        0.03,
    )

    assert (key, count) == ("RIGHT", 3)


def test_keypress_batch_preserves_next_different_key():
    keyboard_input._PENDING_KEYS.clear()
    keys = iter(["RIGHT", "\r"])
    first_availability = iter([True])

    first = keyboard_input._read_keypress_batch_impl(
        lambda: next(keys),
        lambda _timeout_s: next(first_availability),
        0.03,
    )
    second = keyboard_input._read_keypress_batch_impl(
        lambda: next(keys),
        lambda _timeout_s: False,
        0.03,
    )

    assert first == ("RIGHT", 1)
    assert second == ("\r", 1)
