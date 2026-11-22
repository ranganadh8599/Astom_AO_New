"""Checkpointer selection, plus real Postgres persistence.

Two layers, deliberately separated:

* **Always run** — ``open_checkpointer`` picks the right backend, and every failure mode
  (missing DSN, unsupported backend, missing optional extra) raises a message that says
  what to do. No database required.
* **Integration** — skipped unless ``ORCH_TEST_POSTGRES_DSN`` is set. That variable is
  read *only* here, never by application code, so ``.env`` pointing at a live database
  cannot make the suite depend on one.

Integration tests use unique thread ids and delete their own rows, so they are safe to run
against a database that also holds real conversations.

Windows note: psycopg refuses the ProactorEventLoop, which is also the loop
``pytest-asyncio`` gives an ``async def`` test here. Every integration test is therefore a
*sync* test that drives a ``SelectorEventLoop`` itself, mirroring
``orchestrator/__main__.py``.
"""

from __future__ import annotations

import asyncio
import operator
import os
import sys
import uuid
from typing import Annotated, Any, Iterator, TypedDict

import pytest

from orchestrator.config import Settings
from orchestrator.graph import open_checkpointer
from orchestrator.graph.checkpointer import open_checkpointer as direct_open
from orchestrator.graph.checkpointer import _ensure_database as direct_ensure

from tests.conftest import FakeGateway, make_settings

TEST_DSN = os.environ.get("ORCH_TEST_POSTGRES_DSN", "")

requires_postgres = pytest.mark.skipif(
    not TEST_DSN,
    reason="set ORCH_TEST_POSTGRES_DSN=postgresql://user:pass@host:5432/db to run",
)


def _loop_factory() -> Any:
    """Selector on Windows, interpreter default elsewhere — same as the entry point."""
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def run(coro) -> Any:
    """Drive a coroutine on a compatible loop, on any platform."""
    with asyncio.Runner(loop_factory=_loop_factory()) as runner:
        return runner.run(coro)


def _thread_id(label: str) -> str:
    return f"pytest-{label}-{uuid.uuid4().hex[:12]}"


# -- a minimal graph: the real write path, not hand-built checkpoints ------


class EchoState(TypedDict, total=False):
    history: Annotated[list[dict[str, Any]], operator.add]


def _echo_graph(saver):
    """The smallest graph that accumulates ``history`` the way the orchestrator does."""
    from langgraph.graph import END, START, StateGraph

    def echo(state: EchoState) -> dict[str, Any]:
        turns = len(state.get("history") or [])
        return {"history": [{"role": "assistant", "content": f"echo {turns}"}]}

    builder = StateGraph(EchoState)
    builder.add_node("echo", echo)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    return builder.compile(checkpointer=saver)


# -- backend selection (no database) --------------------------------------


async def test_memory_backend_yields_in_memory_saver() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    async with open_checkpointer(make_settings(checkpoint_backend="memory")) as (saver, health):
        assert isinstance(saver, InMemorySaver)
        assert health.cached().reachable is True


async def test_memory_is_the_default() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    async with open_checkpointer(make_settings()) as (saver, health):
        assert isinstance(saver, InMemorySaver)
        assert health.cached().backend == "memory"


def test_postgres_without_dsn_is_refused_before_connecting() -> None:
    """Fails on config, not on a TCP timeout to a host that was never named."""

    async def go() -> None:
        async with open_checkpointer(
            make_settings(checkpoint_backend="postgres", postgres_dsn="")
        ):
            pytest.fail("should not reach the connection attempt")

    with pytest.raises(RuntimeError, match="POSTGRES_DSN"):
        run(go())


def test_unsupported_backend_names_the_alternatives() -> None:
    async def go() -> None:
        async with open_checkpointer(make_settings(checkpoint_backend="sqlite")):
            pytest.fail("should not open")

    with pytest.raises(RuntimeError, match="memory.*postgres|postgres.*memory"):
        run(go())


def test_missing_optional_extra_is_explained(monkeypatch) -> None:
    """A bare ImportError is a support ticket; the hint is the fix."""
    import builtins

    real_import = builtins.__import__

    def deny(name: str, *args: Any, **kwargs: Any):
        if name.startswith("langgraph.checkpoint.postgres"):
            raise ImportError("No module named 'langgraph.checkpoint.postgres'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)

    async def go() -> None:
        async with open_checkpointer(
            make_settings(
                checkpoint_backend="postgres",
                postgres_dsn="postgresql://u:p@127.0.0.1:1/db",
            )
        ):
            pytest.fail("should not open")

    with pytest.raises(RuntimeError, match=r'pip install -e "\.\[postgres\]"'):
        run(go())


def test_graph_reexports_the_same_opener() -> None:
    assert direct_open is open_checkpointer


# -- database auto-creation -------------------------------------------------


def test_auto_create_defaults_to_on() -> None:
    assert make_settings().postgres_auto_create is True


def test_auto_create_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_AUTO_CREATE", "0")
    from orchestrator.config import Settings as FreshSettings

    assert FreshSettings.from_env().postgres_auto_create is False


async def test_auto_create_skips_a_memory_backend() -> None:
    """No DSN handling on the memory path: it must not touch a database at all."""
    from langgraph.checkpoint.memory import InMemorySaver

    async with open_checkpointer(make_settings(checkpoint_backend="memory")) as (saver, health):
        assert isinstance(saver, InMemorySaver)
        assert health.cached().reachable is True


def test_auto_create_ignores_a_malformed_dsn() -> None:
    """A DSN the parser cannot read is left for the real connection to report."""
    from orchestrator.graph.checkpointer import _ensure_database

    # Must not raise: parsing fails, so there is nothing safe to create.
    run(_ensure_database("not a dsn at all"))


def test_auto_create_refuses_when_maintenance_db_is_unreachable(monkeypatch) -> None:
    """Bad credentials must name the fix, not surface a bare driver error."""
    import psycopg

    async def refuse(*args, **kwargs):
        raise psycopg.OperationalError("password authentication failed")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", refuse)

    async def go() -> None:
        await direct_ensure("postgresql://nobody:nopass@db.internal:5432/orch_x")

    with pytest.raises(RuntimeError, match="POSTGRES_AUTO_CREATE=0"):
        run(go())


def test_auto_create_reports_missing_createdb_privilege(monkeypatch) -> None:
    """Managed Postgres: say what to create, not 'permission denied'."""
    import psycopg

    class Cursor:
        async def fetchone(self):
            return None

    class Conn:
        async def execute(self, query, params=None):
            if "create database" in str(query).lower():
                raise psycopg.errors.InsufficientPrivilege("permission denied")
            return Cursor()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_connect(*args, **kwargs):
        return Conn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", fake_connect)

    async def go() -> None:
        await direct_ensure("postgresql://app:secret@db.internal:5432/orch_x")

    with pytest.raises(RuntimeError, match=r"CREATE DATABASE orch_x"):
        run(go())


# -- real Postgres (opt-in) -----------------------------------------------


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"checkpoint_backend": "postgres", "postgres_dsn": TEST_DSN}
    base.update(overrides)
    return make_settings(**base)


@pytest.fixture
def cleanup_threads() -> Iterator[list[str]]:
    """Delete the rows these tests create, so a shared database stays readable."""
    created: list[str] = []
    yield created

    if not created:
        return
    try:
        import psycopg
    except ImportError:  # pragma: no cover - the extra is installed with the marker
        return
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        for thread_id in created:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                conn.execute(
                    f"delete from {table} where thread_id = %s", (thread_id,)
                )


@requires_postgres
def test_setup_creates_the_checkpoint_tables(cleanup_threads: list[str]) -> None:
    import psycopg

    async def go() -> None:
        async with open_checkpointer(_settings()):
            pass

    run(go())

    with psycopg.connect(TEST_DSN) as conn:
        rows = conn.execute(
            "select tablename from pg_tables where schemaname = 'public'"
        ).fetchall()
    tables = {row[0] for row in rows}

    assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} <= tables


@requires_postgres
def test_missing_database_is_created_on_boot() -> None:
    """End to end: point at a database that does not exist and boot normally.

    Covers the whole first-run path — database created, tables created — which no
    manual provisioning step is needed for.
    """
    import psycopg
    from psycopg import sql

    name = f"pytest_db_{uuid.uuid4().hex[:10]}"
    admin = TEST_DSN  # any DSN whose role may create databases

    try:
        async def go() -> None:
            async with open_checkpointer(_settings(postgres_dsn=_dsn_for(name))):
                pass

        run(go())

        with psycopg.connect(admin, autocommit=True) as conn:
            exists = conn.execute(
                "select 1 from pg_database where datname = %s", (name,)
            ).fetchone()
            assert exists, "the orchestrator did not create the database"

        # Connect to the new database and confirm the schema came with it.
        with psycopg.connect(_dsn_for(name)) as conn:
            rows = conn.execute(
                "select tablename from pg_tables where schemaname = 'public'"
            ).fetchall()
        tables = {row[0] for row in rows}
        assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} <= tables
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("drop database if exists {}").format(sql.Identifier(name))
            )


def _dsn_for(dbname: str) -> str:
    """Rewrite the test DSN's database name."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    return make_conninfo(**{**conninfo_to_dict(TEST_DSN), "dbname": dbname})


@requires_postgres
def test_history_survives_a_new_connection(cleanup_threads: list[str]) -> None:
    """The core promise: state written by one connection is read by another."""
    thread = _thread_id("roundtrip")
    cleanup_threads.append(thread)
    config = {"configurable": {"thread_id": thread}}

    async def write_then_read() -> list[dict[str, Any]]:
        async with open_checkpointer(_settings()) as (saver, _health):
            await _echo_graph(saver).ainvoke(
                {"history": [{"role": "user", "content": "remember me"}]}, config
            )
        # Connection and graph are gone; anything readable now came from Postgres.

        async with open_checkpointer(_settings()) as (reopened, _health):
            state = await _echo_graph(reopened).aget_state(config)
        return list(state.values.get("history") or [])

    history = run(write_then_read())

    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "remember me"
    assert history[1]["content"] == "echo 1"


@requires_postgres
def test_threads_do_not_share_state(cleanup_threads: list[str]) -> None:
    """Two conversations, one database: each sees only its own history."""
    thread_a = _thread_id("iso-a")
    thread_b = _thread_id("iso-b")
    cleanup_threads.extend([thread_a, thread_b])

    async def go() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cfg_a = {"configurable": {"thread_id": thread_a}}
        cfg_b = {"configurable": {"thread_id": thread_b}}

        async with open_checkpointer(_settings()) as (saver, _health):
            graph = _echo_graph(saver)
            await graph.ainvoke({"history": [{"role": "user", "content": "alpha-only"}]}, cfg_a)
            await graph.ainvoke({"history": [{"role": "user", "content": "beta-only"}]}, cfg_b)
            await graph.ainvoke({"history": [{"role": "user", "content": "alpha-again"}]}, cfg_a)

        async with open_checkpointer(_settings()) as (reopened, _health):
            graph = _echo_graph(reopened)
            a = (await graph.aget_state(cfg_a)).values.get("history") or []
            b = (await graph.aget_state(cfg_b)).values.get("history") or []
        return list(a), list(b)

    history_a, history_b = run(go())

    text_a = [item["content"] for item in history_a]
    text_b = [item["content"] for item in history_b]

    assert text_a[:2] == ["alpha-only", "echo 1"]
    assert "alpha-again" in text_a
    assert text_b[0] == "beta-only"
    assert not any("alpha" in item for item in text_b)


@requires_postgres
def test_orchestrator_restart_keeps_conversation_history(
    fake_gateway: FakeGateway, cleanup_threads: list[str]
) -> None:
    """Two service instances, one conversation: the second must not lose turn one.

    This is what ``InMemorySaver`` cannot do and the reason to run Postgres at all.
    """
    from orchestrator.auth import UserContext
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.service import OrchestratorService

    conversation = _thread_id("restart")
    cleanup_threads.append(conversation)
    user = UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))
    settings = _settings()

    async def one_instance(query: str) -> Any:
        gateway = LiteLLMGateway(settings, client=fake_gateway.client())
        service = OrchestratorService(settings, gateway=gateway)
        await service.__aenter__()
        try:
            return await service.run(query, user, session_id=conversation)
        finally:
            await service.__aexit__(None, None, None)

    first = run(one_instance("how many annual leave days do I get?"))
    second = run(one_instance("and is my expense reimbursement approved?"))

    assert first.status == "completed"
    assert [task["agent_name"] for task in first.tasks] == ["hr-policy-agent"]
    assert second.status == "completed"
    assert [task["agent_name"] for task in second.tasks] == ["finance-agent"]

    async def read_history() -> list[dict[str, Any]]:
        gateway = LiteLLMGateway(settings, client=fake_gateway.client())
        service = OrchestratorService(settings, gateway=gateway)
        await service.__aenter__()
        try:
            state = await service._graph.aget_state(
                {"configurable": {"thread_id": conversation}}
            )
        finally:
            await service.__aexit__(None, None, None)
        return list(state.values.get("history") or [])

    history = run(read_history())
    roles = [item.get("role") for item in history]
    contents = [item.get("content", "") for item in history]

    assert roles == ["user", "assistant", "user", "assistant"]
    assert "annual leave" in contents[0]
    assert "reimbursement" in contents[2]


@requires_postgres
def test_turn_scoped_state_is_not_replayed(
    fake_gateway: FakeGateway, cleanup_threads: list[str]
) -> None:
    """``results`` resets per turn even though ``history`` accumulates.

    Both live in the same checkpoint, so the round-trip has to preserve the distinction
    the ``turn_scoped`` reducer makes in memory.
    """
    from orchestrator.auth import UserContext
    from orchestrator.gateway import LiteLLMGateway
    from orchestrator.service import OrchestratorService

    conversation = _thread_id("turnscope")
    cleanup_threads.append(conversation)
    user = UserContext(oid="oid-1", name="Test User", roles=("AgentUser",))
    settings = _settings()

    async def turn(query: str) -> Any:
        gateway = LiteLLMGateway(settings, client=fake_gateway.client())
        service = OrchestratorService(settings, gateway=gateway)
        await service.__aenter__()
        try:
            return await service.run(query, user, session_id=conversation)
        finally:
            await service.__aexit__(None, None, None)

    run(turn("how many annual leave days do I get?"))
    second = run(turn("and is my expense reimbursement approved?"))

    assert {item["agent_name"] for item in second.results} == {"finance-agent"}


# -- checkpointer health (the /ready signal) -------------------------------


def test_memory_backend_is_always_reachable() -> None:
    from orchestrator.graph.checkpointer import CheckpointerHealth

    health = run(CheckpointerHealth("memory").probe())

    assert health.reachable is True
    assert health.backend == "memory"


def test_cached_state_before_any_probe_is_not_claimed_reachable() -> None:
    """`/health` must not report a Postgres instance healthy before one probe ran."""
    from orchestrator.graph.checkpointer import CheckpointerHealth

    health = CheckpointerHealth("postgres", saver=object())

    cached = health.cached()

    assert cached.backend == "postgres"
    assert cached.reachable is False


def test_probe_failure_is_reported_not_raised() -> None:
    """A dead database must return data, not break the readiness endpoint."""

    class Broken:
        conn = None

    async def go():
        from orchestrator.graph.checkpointer import CheckpointerHealth

        return await CheckpointerHealth("postgres", saver=Broken()).probe()

    health = run(go())

    assert health.reachable is False
    assert "no connection" in health.error


def test_probe_timeout_is_bounded() -> None:
    """A hanging database must not hang /ready — the probe is the outage then."""
    import asyncio as aio

    class Hanging:
        async def execute(self, *_args, **_kwargs):
            await aio.sleep(5)

    class Saver:
        conn = Hanging()

    async def go():
        from orchestrator.graph.checkpointer import CheckpointerHealth

        return await CheckpointerHealth(
            "postgres", saver=Saver(), timeout_s=0.05
        ).probe()

    health = run(go())

    assert health.reachable is False
    assert "timed out" in health.error


def test_probe_result_is_cached_and_force_refreshes() -> None:
    """A load balancer polling every second must not hammer the database."""
    calls = {"n": 0}

    class Cursor:
        async def fetchone(self):
            return (1,)

    class Conn:
        async def execute(self, *_args, **_kwargs):
            calls["n"] += 1
            return Cursor()

    class Saver:
        conn = Conn()

    async def go():
        from orchestrator.graph.checkpointer import CheckpointerHealth

        health = CheckpointerHealth("postgres", saver=Saver(), ttl_s=60.0)
        first = await health.probe()
        second = await health.probe()          # cached
        third = await health.probe(force=True)  # refresh
        return first, second, third

    first, second, third = run(go())

    assert first.reachable and second.reachable and third.reachable
    assert calls["n"] == 2, "cached probe must not re-query"


@requires_postgres
def test_probe_reports_a_live_database() -> None:
    """Integration: the probe against a real pool says reachable."""
    async def go():
        async with open_checkpointer(_settings()) as (_saver, health):
            return await health.probe()

    health = run(go())

    assert health.backend == "postgres"
    assert health.reachable is True
    assert health.error == ""
