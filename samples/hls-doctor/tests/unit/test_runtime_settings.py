import pytest
from pydantic import ValidationError

from hls_doctor.settings.runtime_settings import HlsDoctorSettings


def test_private_targets_optin_is_refused_at_load_inside_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    with pytest.raises(ValidationError) as failure:
        HlsDoctorSettings(hls_allow_private_targets=True)
    assert "HLS_ALLOW_PRIVATE_TARGETS" in str(failure.value)
    assert "container" in str(failure.value).lower()


def test_private_targets_optin_is_accepted_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    settings = HlsDoctorSettings(hls_allow_private_targets=True)
    assert settings.hls_allow_private_targets is True
