import json
import os
import subprocess
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_GATEWAY_URL = "http://localhost:2026"


def _read_json(url: str) -> dict:
    with urllib_request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def recovered_deerflow() -> None:
    subprocess.run([str(REPO_ROOT / "scripts" / "recover_deerflow.sh")], cwd=REPO_ROOT, check=True)


@pytest.mark.skipif(
    os.getenv("AIGIT_RUN_LIVE_DEERFLOW_TESTS") != "1",
    reason="set AIGIT_RUN_LIVE_DEERFLOW_TESTS=1 to run live DeerFlow gateway checks",
)
def test_live_deerflow_agents_endpoint_shape_after_recovery(recovered_deerflow: None) -> None:
    payload = _read_json(f"{LIVE_GATEWAY_URL}/api/agents")

    assert isinstance(payload, dict)
    assert "agents" in payload
    assert isinstance(payload["agents"], list)
    assert payload["agents"]

    agent = payload["agents"][0]
    assert isinstance(agent, dict)
    assert {"name", "description", "model", "tool_groups", "soul"} <= set(agent)
    assert isinstance(agent["name"], str)
    assert isinstance(agent["description"], str)
    assert agent["model"] is None or isinstance(agent["model"], str)
    assert agent["tool_groups"] is None or isinstance(agent["tool_groups"], list)


@pytest.mark.skipif(
    os.getenv("AIGIT_RUN_LIVE_DEERFLOW_TESTS") != "1",
    reason="set AIGIT_RUN_LIVE_DEERFLOW_TESTS=1 to run live DeerFlow gateway checks",
)
def test_live_deerflow_user_profile_endpoint_shape_after_recovery(recovered_deerflow: None) -> None:
    try:
        payload = _read_json(f"{LIVE_GATEWAY_URL}/api/user-profile")
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised against live service
        pytest.fail(f"user-profile endpoint returned HTTP {exc.code}")

    assert isinstance(payload, dict)
    assert "content" in payload
    assert payload["content"] is None or isinstance(payload["content"], str)