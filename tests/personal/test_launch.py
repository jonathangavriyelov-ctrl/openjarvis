"""The one-command personal AI OS launcher stays demo-safe."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_os_up_dry_run_prints_the_dashboard_url():
    script = ROOT / "scripts" / "os-up.sh"
    assert script.is_file()
    completed = subprocess.run(
        ["bash", str(script), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    text = completed.stdout
    assert "http://127.0.0.1:5173/os/world" in text
    assert "hermes3:8b" in text
    assert "No API keys are required." in text
    assert "backend=" in text
    makefile = (ROOT / "Makefile").read_text()
    assert "scripts/os-up.sh" in makefile
    source = script.read_text()
    assert "nohup" in source
    assert "disown" in source
    assert "Ready:" in source
    assert "trap cleanup" not in source
    assert "\nwait\n" not in source


def test_local_app_serves_the_desk_without_keys(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from openjarvis.personal.local_app import create_app

    monkeypatch.setenv("OPENJARVIS_PERSONAL_DB", str(tmp_path / "os.db"))
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("HF_KEY", raising=False)
    app = create_app(probe_ollama=False)
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    report = client.get("/v1/personal/roi")
    assert report.status_code == 200, report.text
    assert report.json()["overall"]["paying"] is False
    worlds = client.get("/v1/personal/worlds")
    names = {world["name"] for world in worlds.json()["worlds"]}
    assert "Quick Funders" in names
