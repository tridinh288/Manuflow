"""The seed only runs in ENV=dev with a demo password of at least 10 characters."""

import pytest

import seed.__main__ as seed_cli
from app.core.config import Environment, Settings


def test_b16_seed_refuses_outside_dev(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert settings.env is Environment.TEST
    monkeypatch.setattr(seed_cli, "get_settings", lambda: settings)
    monkeypatch.setenv(seed_cli.PASSWORD_ENV, "long-enough-password")
    assert seed_cli.main() == 1
    assert "ENV must be dev" in capsys.readouterr().err


@pytest.mark.parametrize("password", [None, "", "short-pw1"])
def test_b16_seed_requires_a_ten_character_password(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    password: str | None,
) -> None:
    dev = settings.model_copy(update={"env": Environment.DEV})
    monkeypatch.setattr(seed_cli, "get_settings", lambda: dev)
    if password is None:
        monkeypatch.delenv(seed_cli.PASSWORD_ENV, raising=False)
    else:
        monkeypatch.setenv(seed_cli.PASSWORD_ENV, password)
    assert seed_cli.main() == 1
    err = capsys.readouterr().err
    assert "SEED_DEMO_PASSWORD" in err
    if password:
        assert password not in err  # never echoed
