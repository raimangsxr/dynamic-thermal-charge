from dynamic_thermal_charge.entrypoints import initialise_storage
from dynamic_thermal_charge.persistence.bootstrap import open_store
from dynamic_thermal_charge.persistence.paths import StorePaths


def test_storage_entrypoint_initialises_the_shared_store_idempotently(tmp_path, monkeypatch):
    paths = StorePaths.in_directory(tmp_path / "state")
    monkeypatch.setattr(StorePaths, "production", classmethod(lambda cls: paths))
    monkeypatch.setenv("DTC_API_TOKEN", "a" * 40)

    initialise_storage()
    first = open_store(paths)
    config, revision = first.repository.current()
    snapshot = first.system_configuration.current()

    initialise_storage()
    second = open_store(paths)

    assert len(config.heaters) > 0
    assert revision == second.repository.current()[1]
    assert snapshot.revision == second.system_configuration.current().revision
    assert snapshot.secrets["admin_token_digest"].value
