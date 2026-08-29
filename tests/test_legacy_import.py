import json

from dynamic_thermal_charge.persistence.bootstrap import initialise_legacy, open_legacy_store, open_store
from dynamic_thermal_charge.persistence.legacy_import import import_legacy
from dynamic_thermal_charge.persistence.paths import StorePaths


def _legacy_installation(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    store = open_legacy_store({"DTC_DATABASE_URL": url})
    initialise_legacy(store)
    environment = tmp_path / "legacy.environment"
    environment.write_text(
        "\n".join([
            f"DTC_DATABASE_URL={url}",
            f"DTC_API_TOKEN={'a' * 40}",
            "DTC_API_HOST=0.0.0.0",
            "DTC_MQTT_HOST=broker.local",
            "DTC_MQTT_USERNAME=dtc",
            "DTC_MQTT_PASSWORD=sentinel-password",
            "AEMET_API_KEY=sentinel-aemet",
        ])
    )
    return store, environment


def test_legacy_import_dry_run_is_sanitized_and_non_mutating(tmp_path):
    _source, environment = _legacy_installation(tmp_path)
    paths = StorePaths.in_directory(tmp_path / "target")
    report = import_legacy(environment, paths, apply=False)
    serialized = json.dumps(report.public_dict())
    assert report.installation_present is True
    assert report.table_counts["installation"] == 1
    assert "sentinel-password" not in serialized
    assert not paths.bootstrap.exists()


def test_legacy_import_preserves_configuration_and_is_idempotent(tmp_path):
    source, environment = _legacy_installation(tmp_path)
    paths = StorePaths.in_directory(tmp_path / "target")
    report = import_legacy(environment, paths, apply=True)
    target = open_store(paths)
    assert target.repository.current() == source.repository.current()
    public = target.system_configuration.public_snapshot()
    assert public["sections"]["api"]["host"] == "0.0.0.0"
    assert public["sections"]["mqtt"]["host"] == "broker.local"
    assert public["secrets"]["mqtt_password"]["configured"] is True
    assert "sentinel-password" not in json.dumps(public)
    repeated = import_legacy(environment, paths, apply=True)
    assert repeated.already_imported is True
