"""The Postgres checkpointer plus the two things that keep it honest.

Why a pool is constructed here
-----------------------------
``AsyncPostgresSaver.from_conn_string`` opens a single connection and keeps it. When
Postgres restarts, the server drops it and the next ``aget_tuple`` raises
``consuming input failed: server closed the connection unexpectedly``. Measured: every
subsequent turn returned 500 until the process was restarted, while both ``/health`` and
``/ready`` still reported healthy.

A ``psycopg_pool.AsyncConnectionPool`` with ``check=check_connection`` and a
``max_lifetime`` replaces a dead connection on checkout instead of handing it out, so the
instance recovers on its own.

Why ``/ready`` asks instead of assuming
--------------------------------------
Boot success is not proof of health. ``CheckpointerHealth`` is a cheap, cached
``SELECT 1`` that ``/ready`` consults — never ``/health``, because a database blip must
remove the instance from rotation, not restart the container.

What is created automatically
-----------------------------
``AsyncPostgresSaver.setup()`` creates the *tables* (``checkpoints``,
``checkpoint_blobs``, ``checkpoint_writes``, ``checkpoint_migrations``) on an empty
database — LangGraph owns that schema and migrates it.

The *database* is a different story: psycopg fails first with
``database "<name>" does not exist``. ``POSTGRES_AUTO_CREATE`` (default on) connects to
the ``postgres`` maintenance database with the same credentials and issues ``CREATE
DATABASE`` only when needed. Set ``POSTGRES_AUTO_CREATE=0`` where the role lacks CREATEDB;
the failure then names what to create by hand.

Which database?
---------------
There is no database-name setting. It comes from the DSN's path segment:

    postgresql://user:pass@host:5432/orchestrator
                                     ^^^^^^^^^^^^ dbname

Omitting it is not an error — libpq falls back to the *user* name, so a role called
``postgres`` would silently write checkpoint tables into the ``postgres`` maintenance
database. Auto-creation skips in that case (nothing to create), which is why the DSN
should always name the database explicitly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from langgraph.checkpoint.memory import InMemorySaver

from orchestrator.config import Settings

log = logging.getLogger(__name__)

# How long a probe result may be reused. /ready is called on a fixed interval by load
# balancers; without this, a burst of probes hammers a database already struggling.
# Same reasoning as SEARCH_UNAVAILABLE_TTL_S.
PROBE_TTL_S = 5.0
# A readiness probe must answer quickly or it *becomes* the outage. A warm probe is 1-2ms;
# the slow case is a *cold* reconnect after the server dropped the connection, which was
# measured over 2s once on a long-running process (a fresh pool does it in 54ms). A bound
# tight enough to fail that produces a false `not_ready`, which removes a healthy instance
# from rotation — worse than a probe that occasionally takes a few seconds. Load balancers
# commonly allow 5-10s.
PROBE_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class MemoryHealth:
    """Checkpointer state as reported on ``/ready``.

    ``reachable`` is connectivity *now*, not configuration — ``"postgres"`` in
    ``/health`` only says which backend was selected at boot.
    """

    backend: str
    reachable: bool = True
    error: str = ""
    checked_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "reachable": self.reachable,
            "error": self.error,
            "checked_at": self.checked_at,
        }


class CheckpointerHealth:
    """Cached connectivity probe for the checkpointer.

    A memory backend has no external dependency, so it is always reachable. Postgres is
    probed with ``SELECT 1`` through the saver's pool, bounded by ``PROBE_TIMEOUT_S`` and
    memoised for ``PROBE_TTL_S``.
    """

    def __init__(
        self,
        backend: str,
        *,
        saver: Any = None,
        ttl_s: float = PROBE_TTL_S,
        timeout_s: float = PROBE_TIMEOUT_S,
        clock=time.monotonic,
    ) -> None:
        self._backend = backend
        self._saver = saver
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s
        self._clock = clock
        self._last: MemoryHealth | None = None
        self._checked: float = 0.0

    async def probe(self, *, force: bool = False) -> MemoryHealth:
        if self._backend == "memory":
            return MemoryHealth(
                backend="memory", reachable=True, checked_at=time.time()
            )

        if not force and self._last is not None:
            if (self._clock() - self._checked) < self._ttl_s:
                return self._last

        reachable = True
        error = ""
        try:
            conn = getattr(self._saver, "conn", None)
            if conn is None:
                raise RuntimeError("checkpointer has no connection to probe")
            cursor = await asyncio.wait_for(
                self._execute_probe(conn), timeout=self._timeout_s
            )
            await cursor.fetchone()
        except asyncio.TimeoutError:
            reachable = False
            error = f"probe timed out after {self._timeout_s:g}s"
        except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
            reachable = False
            first_line = str(exc).strip().splitlines()
            error = (first_line[0][:200] if first_line else type(exc).__name__)

        self._checked = self._clock()
        self._last = MemoryHealth(
            backend=self._backend,
            reachable=reachable,
            error=error,
            checked_at=time.time(),
        )
        if not reachable:
            log.warning("checkpointer unreachable: %s", error)
        return self._last

    def cached(self) -> MemoryHealth:
        """Last known state without touching the database (for ``/health``)."""
        if self._last is not None:
            return self._last
        return MemoryHealth(
            backend=self._backend,
            reachable=self._backend == "memory",
            checked_at=0.0,
        )

    @staticmethod
    async def _execute_probe(conn: Any) -> Any:
        """Run ``select 1`` on whichever shape the saver holds.

        ``AsyncPostgresSaver`` stores either a bare connection or an
        ``AsyncConnectionPool`` in ``.conn``. Only the pool has ``.connection()``, and
        going through it means a dead member is replaced on checkout rather than probed
        — the same repair path the graph takes, so a green probe really does predict a
        working turn.
        """
        if hasattr(conn, "connection"):
            async with conn.connection() as live:
                return await live.execute("select 1")
        return await conn.execute("select 1")


async def _ensure_database(dsn: str, *, maintenance_db: str = "postgres") -> None:
    """Create the DSN's database if it does not exist.

    The database name is read from the DSN's path (``conninfo_to_dict`` -> ``dbname``);
    there is no separate setting. When the path is empty the name is absent, libpq
    connects to a database named after the user, and this function does nothing — so a
    DSN without a database name silently targets the maintenance database instead of
    failing.

    Idempotent and safe to race: two instances starting together both check, both see
    nothing, and the loser's ``CREATE DATABASE`` is swallowed as ``DuplicateDatabase``.
    Any other failure is reported with the manual fix, because "permission denied to
    create database" is not something a retry resolves.
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    try:
        params = conninfo_to_dict(dsn)
    except Exception:  # pragma: no cover - malformed DSN, let the real connect explain
        return

    dbname = params.get("dbname") or ""
    if not dbname or dbname == maintenance_db:
        return

    maintenance = make_conninfo(**{**params, "dbname": maintenance_db})

    try:
        conn = await psycopg.AsyncConnection.connect(maintenance, autocommit=True)
    except psycopg.OperationalError as exc:
        # Usually "database postgres does not exist" on a non-standard server, or bad
        # credentials. Neither is fixed by guessing, so surface the original message.
        raise RuntimeError(
            f"cannot reach the maintenance database {maintenance_db!r} to create "
            f"{dbname!r}: {exc}. Create the database manually, or set "
            "POSTGRES_AUTO_CREATE=0 if it already exists."
        ) from exc

    try:
        async with conn:
            cursor = await conn.execute(
                "select 1 from pg_database where datname = %s", (dbname,)
            )
            if await cursor.fetchone():
                return
            try:
                await conn.execute(
                    sql.SQL("create database {}").format(sql.Identifier(dbname))
                )
                log.info("created database %r", dbname)
            except psycopg.errors.DuplicateDatabase:
                # Another instance won the race between the SELECT and the CREATE.
                log.debug("database %r already created concurrently", dbname)
    except psycopg.errors.InsufficientPrivilege as exc:
        raise RuntimeError(
            f"database {dbname!r} does not exist and this role may not create it "
            f"({exc}). Create it once manually:\n"
            f"  CREATE DATABASE {dbname};\n"
            "or point POSTGRES_DSN at an existing database."
        ) from exc


@asynccontextmanager
async def open_checkpointer(
    settings: Settings,
) -> AsyncIterator[tuple[object, CheckpointerHealth]]:
    """Yield ``(saver, health)``.

    The saver keeps its old shape; ``health`` is new and is what ``/ready`` consults.
    """
    backend = (settings.checkpoint_backend or "memory").lower()

    if backend == "memory":
        saver = InMemorySaver()
        yield saver, CheckpointerHealth("memory", saver=saver)
        return

    if backend != "postgres":
        raise RuntimeError(
            f"unsupported CHECKPOINT_BACKEND={settings.checkpoint_backend!r}; "
            "use 'memory' or 'postgres'"
        )

    if not settings.postgres_dsn:
        raise RuntimeError("CHECKPOINT_BACKEND=postgres requires POSTGRES_DSN")

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError(
            "postgres checkpointing needs the optional extra: "
            'pip install -e ".[postgres]"'
        ) from exc

    # Order matters: the extra check above must win so a missing package reports the
    # install hint rather than a connection error.
    if settings.postgres_auto_create:
        await _ensure_database(settings.postgres_dsn)

    pool = AsyncConnectionPool(
        conninfo=settings.postgres_dsn,
        min_size=1,
        max_size=4,
        # The important pair: a connection whose server went away is discarded on
        # checkout rather than handed to the graph, and one older than max_lifetime is
        # recycled even if it looks fine. Without these, a Postgres restart wedges the
        # process permanently (verified: every turn 500 until restart).
        check=AsyncConnectionPool.check_connection,
        max_lifetime=600.0,
        max_idle=180.0,
        timeout=10.0,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open(wait=True, timeout=15.0)
    try:
        saver = AsyncPostgresSaver(pool)
        # Creates the LangGraph tables on a fresh database — no manual schema setup.
        await saver.setup()
        yield saver, CheckpointerHealth("postgres", saver=saver)
    finally:
        await pool.close()
