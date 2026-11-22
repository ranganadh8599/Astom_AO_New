"""The generated compose file must match the catalogues.

The compose file is the deployment contract: one service per example agent/server, each
with the port and the advertised URL the gateway will dial. It is generated, so the risk is
drift — an agent added to ``catalog.py`` without regenerating never gets deployed, and the
failure is invisible (the container simply does not exist). These tests make that a build
failure instead.

No Docker is needed: ``render()`` is pure string building.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "examples")]

from a2a_suite.catalog import AGENTS  # noqa: E402
from mcp_suite.catalog import SERVERS  # noqa: E402


def _generator():
    """Load ``deploy/gen_suites_compose.py`` by path (it is not an installed package)."""
    path = ROOT / "deploy" / "gen_suites_compose.py"
    spec = importlib.util.spec_from_file_location("gen_suites_compose", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rendered() -> str:
    return _generator().render()


def test_the_shipped_file_is_in_sync(rendered: str) -> None:
    """Regenerating must be a no-op; ``--check`` in CI depends on this."""
    shipped = (ROOT / "docker-compose.suites.yml").read_text(encoding="utf-8")
    assert shipped == rendered, "run: python deploy/gen_suites_compose.py"


def test_every_a2a_agent_is_a_service_with_its_own_port(rendered: str) -> None:
    for entry in AGENTS:
        assert f"  a2a-{entry.id}:\n" in rendered, entry.id
        # The card must advertise the name the gateway resolves, never localhost.
        assert f'      - "--url"\n      - "http://a2a-{entry.id}:{entry.port}"' in rendered, entry.id
        assert f'      - "--port"\n      - "{entry.port}"' in rendered, entry.id


def test_every_mcp_server_is_a_service_with_its_module(rendered: str) -> None:
    for entry in SERVERS:
        module = f"mcp_suite.servers.{entry.id.replace('-', '_')}"
        assert f"  mcp-{entry.id}:\n" in rendered, entry.id
        assert module in rendered, entry.id
        assert f'PORT: "{entry.port}"' in rendered, entry.id


def test_ports_are_unique_across_both_suites() -> None:
    """A collision would make one container fail to bind at runtime, not at build time."""
    ports = [entry.port for entry in AGENTS] + [entry.port for entry in SERVERS]
    assert len(ports) == len(set(ports)), sorted(p for p in ports if ports.count(p) > 1)


def test_the_service_count_matches_the_catalogues(rendered: str) -> None:
    services = [line for line in rendered.splitlines() if line.startswith("  a2a-")
                or line.startswith("  mcp-")]
    assert len(services) == len(AGENTS) + len(SERVERS) == 40


def test_healthcheck_is_kind_aware(rendered: str) -> None:
    """One image serves two protocols; the probe must know which it is watching."""
    assert 'SUITE_KIND: a2a' in rendered and 'SUITE_KIND: mcp' in rendered
