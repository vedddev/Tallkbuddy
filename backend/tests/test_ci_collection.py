"""A clean CI checkout can collect tests without live provider credentials."""

import runpy
from pathlib import Path

import dotenv
import groq


SCRIPT = Path(__file__).resolve().parents[1] / "test_groq.py"


def test_manual_groq_script_import_has_no_side_effects(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("A live provider or dotenv call occurred during test collection")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(groq, "Groq", forbidden)
    runpy.run_path(str(SCRIPT), run_name="pytest_collection")


def test_manual_groq_script_requires_key_only_when_run(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    namespace = runpy.run_path(str(SCRIPT), run_name="pytest_collection")
    assert namespace["main"]() == 1
    assert "not configured" in capsys.readouterr().out
