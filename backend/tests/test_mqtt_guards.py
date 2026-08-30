"""Static isolation guards for the harmless MQTT process."""

import ast
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "src" / "dynamic_thermal_charge"
MQTT = SOURCE / "mqtt"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_mqtt_package_cannot_import_hardware_or_controller_modules():
    forbidden = {"controller", "drivers", "gpio_driver"}
    offenders = {}
    for path in MQTT.glob("*.py"):
        leaked = {
            name for name in _imports(path)
            if any(part in forbidden for part in name.split("."))
        }
        if leaked:
            offenders[path.name] = leaked
    assert not offenders


def test_only_the_optional_adapter_may_import_paho():
    offenders = []
    for path in SOURCE.rglob("*.py"):
        if path == MQTT / "client.py":
            continue
        if any(name.startswith("paho") for name in _imports(path)):
            offenders.append(path)
    assert not offenders


def test_core_and_runtime_import_when_paho_is_unavailable():
    code = """
import sys
class BlockPaho:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'paho' or fullname.startswith('paho.'):
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, BlockPaho())
import dynamic_thermal_charge
import dynamic_thermal_charge.runtime
import dynamic_thermal_charge.mqtt
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)
