"""Phase 1 configuration contract for the four controls."""

import pytest

from harness.__main__ import _cmd_doctor
from harness.config import Config


def test_four_controls_config_defaults_and_doctor_output(tmp_path, capsys):
    cfg = Config(
        workspace_roots=[tmp_path], state_dir=tmp_path / "state", secret_route="r"
    )

    assert cfg.effort_profiles == {
        "low": 2, "medium": 8, "high": 16, "xhigh": 32, "max": 50,
    }
    assert cfg.model_concurrency == 1
    assert cfg.decision_caps == {
        "build": 0.2, "review": 0.8, "plan": 0.8, "research": 0.8,
    }

    _cmd_doctor(cfg)
    output = capsys.readouterr().out
    assert "effort_profiles:" in output
    assert "model_concurrency: 1" in output
    assert "decision_caps:" in output


def test_four_controls_config_loads_json_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_SECRET_ROUTE", "r")
    monkeypatch.setenv(
        "HARNESS_EFFORT_PROFILES",
        '{"low":3,"medium":9,"high":18,"xhigh":36,"max":60}',
    )
    monkeypatch.setenv("HARNESS_MODEL_CONCURRENCY", "2")
    monkeypatch.setenv(
        "HARNESS_DECISION_CAPS",
        '{"build":0.1,"review":1.0,"plan":0.7,"research":0.9}',
    )

    cfg = Config.from_env(load_dotenv=False)

    assert cfg.effort_profiles == {
        "low": 3, "medium": 9, "high": 18, "xhigh": 36, "max": 60,
    }
    assert cfg.model_concurrency == 2
    assert cfg.decision_caps == {
        "build": 0.1, "review": 1.0, "plan": 0.7, "research": 0.9,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("effort_profiles", {"low": 0}, "positive integers"),
        ("effort_profiles", {"low": True}, "positive integers"),
        ("model_concurrency", 0, "at least 1"),
        ("decision_caps", {"build": 0}, "greater than 0 and at most 1"),
        ("decision_caps", {"build": 1.1}, "greater than 0 and at most 1"),
    ],
)
def test_four_controls_config_rejects_invalid_values(tmp_path, field, value, message):
    kwargs = {
        "workspace_roots": [tmp_path],
        "state_dir": tmp_path / "state",
        "secret_route": "r",
        field: value,
    }
    with pytest.raises(ValueError, match=message):
        Config(**kwargs)


def test_four_controls_config_rejects_invalid_json_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_SECRET_ROUTE", "r")
    monkeypatch.setenv("HARNESS_EFFORT_PROFILES", "not-json")

    with pytest.raises(ValueError, match="HARNESS_EFFORT_PROFILES must be a JSON object"):
        Config.from_env(load_dotenv=False)
