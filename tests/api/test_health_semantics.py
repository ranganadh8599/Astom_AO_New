"""Liveness vs readiness.

Two endpoints with deliberately different failure semantics, because conflating them
causes two opposite outages:

* `/health` — liveness. Always 200 while the process runs. If this failed on a
  `degraded` model check, the platform would restart the container in a loop for
  something a retry fixes.
* `/ready` — readiness. 503 only when the instance cannot serve traffic. That is
  *only* a rejected model: the fault is permanent, every turn would fail, so traffic
  should go elsewhere while the pod stays alive for debugging.

`degraded` (gateway unreachable) must stay READY. The gateway being briefly down is not
this instance's fault, and pulling every pod from rotation would turn one blip into a
full outage.
"""

from __future__ import annotations

import pytest

from orchestrator.service import ModelCheck


@pytest.mark.parametrize(
    ("status", "healthy", "serves_traffic"),
    [
        ("pending", True, True),   # check still running: normal startup
        ("ok", True, True),
        # degraded: the gateway could not be reached. Not provably healthy, but the
        # gateway may well be fine, so traffic should keep flowing.
        ("degraded", False, True),
        ("failed", False, False),  # rejected model: permanently broken
    ],
)
def test_status_semantics(status: str, healthy: bool, serves_traffic: bool) -> None:
    check = ModelCheck(status=status)

    assert check.healthy is healthy
    assert check.serves_traffic is serves_traffic


def test_degraded_serves_traffic_without_claiming_health() -> None:
    """The nuance worth guarding: not provably healthy, still in rotation."""
    check = ModelCheck(status="degraded", warnings=("could not verify model x",))

    assert not check.healthy
    assert check.serves_traffic
    assert check.warnings


def test_failed_carries_the_reason() -> None:
    check = ModelCheck(status="failed", error="gateway rejected model 'x'")

    assert not check.serves_traffic
    assert "rejected" in check.error
