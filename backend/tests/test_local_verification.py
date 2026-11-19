"""The local smoke harness must use valid input and refuse unsafe targets."""

from pydantic import TypeAdapter, EmailStr

from scripts import local_verification


def test_generated_local_test_email_passes_registration_validation() -> None:
    email = local_verification.make_test_email()
    assert TypeAdapter(EmailStr).validate_python(email) == email


def test_local_smoke_refuses_nonlocal_database(monkeypatch, capsys) -> None:
    class Settings:
        app_env = "development"
        database_url = "postgresql+asyncpg://user:private@remote.example/talkbuddy"

    monkeypatch.setattr(local_verification, "Settings", Settings)
    assert local_verification.main() == 2
    assert "private" not in capsys.readouterr().out
