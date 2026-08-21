import argparse

import pytest

from recorder.recorder import parse_recording_windows


def test_parse_recording_windows():
    assert parse_recording_windows("14-21, 44-51") == [
        (14, 21),
        (44, 51),
    ]


@pytest.mark.parametrize("value", ["", "14", "14-60", "x-y"])
def test_parse_recording_windows_rejects_invalid_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_recording_windows(value)