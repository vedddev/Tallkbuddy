"""Staging checks must be opt-in and must not leak private values."""

from scripts import staging_smoke


def test_staging_smoke_requires_explicit_confirmation(monkeypatch, capsys) -> None:
    monkeypatch.setenv("STAGING_ORIGIN", "https://staging.invalid")
    monkeypatch.setenv("STAGING_TEST_EMAIL", "private@example.invalid")
    monkeypatch.setenv("STAGING_TEST_PASSWORD", "private-password")
    monkeypatch.delenv("STAGING_CONFIRM", raising=False)
    monkeypatch.setattr(staging_smoke.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("network")))
    assert staging_smoke.main() == 2
    output = capsys.readouterr().out
    assert "private-password" not in output
    assert "private@example.invalid" not in output


def test_staging_smoke_requires_https(monkeypatch) -> None:
    monkeypatch.setenv("STAGING_ORIGIN", "http://staging.invalid")
    monkeypatch.setenv("STAGING_TEST_EMAIL", "private@example.invalid")
    monkeypatch.setenv("STAGING_TEST_PASSWORD", "private-password")
    monkeypatch.setenv("STAGING_CONFIRM", "1")
    monkeypatch.setattr(staging_smoke.httpx, "Client", lambda **_: (_ for _ in ()).throw(AssertionError("network")))
    assert staging_smoke.main() == 2
