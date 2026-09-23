"""Checks for reproducible production dependency and image delivery inputs."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_delivery_check_accepts_the_checked_in_contract():
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "check_delivery.py")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
