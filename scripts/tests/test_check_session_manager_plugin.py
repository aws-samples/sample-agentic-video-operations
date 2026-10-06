import subprocess

import check_prerequisites as doctor


def test_session_manager_plugin_reports_its_version(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        doctor,
        "run_command",
        lambda *_command: subprocess.CompletedProcess([], 0, "1.2.707.0\n", ""),
    )

    result = doctor.check_session_manager_plugin()

    assert result.passed
    assert result.group is doctor.CheckGroup.AWS
    assert result.detail == "1.2.707.0"


def test_session_manager_plugin_is_a_failed_check_when_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)

    result = doctor.check_session_manager_plugin()

    assert not result.passed
    assert result.group is doctor.CheckGroup.AWS
    assert result.detail == "not found"
    assert "install-plugin" in result.fix
