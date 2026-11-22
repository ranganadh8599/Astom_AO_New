"""Register the containerised example suites on the gateway, then grant them.

Run this after ``docker compose -f docker-compose.suites.yml up -d``. It is the bridge
between the compose file and the gateway's registry: containers exist, but the registry
still holds whatever URL was there before (usually ``host.docker.internal:<port>`` from a
host run). Repointing matters — the card the gateway fetches must advertise an address the
*container* can dial.

    .\\.venv\\Scripts\\python.exe deploy/register_examples.py --dry-run
    .\\.venv\\Scripts\\python.exe deploy/register_examples.py --grant
    .\\.venv\\Scripts\\python.exe deploy/register_examples.py --verify-only

What it does, idempotently:

1. A2A — builds each card **locally from the catalogue and the agent's own SPEC** (no HTTP:
   the host cannot resolve the compose service names, and fetching through localhost would
   only work if ports were published), then POSTs or PUTs it with
   ``url=http://a2a-<id>:<port>``.
2. MCP — upserts ``server_name=<id with underscores>`` with
   ``url=http://mcp-<id>:<port>/mcp``. Hyphens are illegal in a server name; grants are by
   name, so the underscore form is the stable identity.
3. Grants — adds the ids/names to the team and then the key, **unioned** with what is
   already there so unrelated targets (``ronaldo-agent``, ``field_ops``) are not dropped.
4. Verifies — lists agents and tools *with the virtual key*, which is what the orchestrator
   actually sees.

Admin key needed for 1-3; verification uses the virtual key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "examples"), str(ROOT)]

import httpx  # noqa: E402

from a2a_suite.catalog import AGENTS  # noqa: E402
from a2a_suite.server import load_spec  # noqa: E402
from mcp_suite.catalog import SERVERS  # noqa: E402
from orchestrator.admin import onboarding as ob  # noqa: E402
from orchestrator.config import Settings, load_dotenv  # noqa: E402

# A host template, not a full URL: the port comes from the catalogue, so the two cannot
# disagree. `{id}` is the compose service name for containers, or a plain hostname
# (`localhost`, `host.docker.internal`) for a host-run suite.
A2A_HOST = "a2a-{id}"
MCP_HOST = "mcp-{id}"


def _host(template: str, entry_id: str) -> str:
    return template.format(id=entry_id, port="")


def a2a_url(agent_id: str, port: int, template: str) -> str:
    return f"http://{_host(template, agent_id)}:{port}"


def mcp_url(server_id: str, port: int, template: str) -> str:
    return f"http://{_host(template, server_id)}:{port}/mcp"


def mcp_name(server_id: str) -> str:
    return server_id.replace("-", "_")


async def _existing(gateway: str, admin: str) -> tuple[dict[str, dict], dict[str, dict]]:
    async with httpx.AsyncClient(base_url=gateway.rstrip("/"), timeout=60.0,
                                 headers={"authorization": f"Bearer {admin}"}) as http:
        agents = {a.get("agent_name"): a for a in (await http.get("/v1/agents")).json()}
        servers = {s.get("server_name"): s for s in (await http.get("/v1/mcp/server")).json()}
    return agents, servers


async def register_a2a(
    gateway: str, admin: str, *, host: str, protocol_version: str, dry_run: bool,
    existing: dict[str, dict],
) -> list[tuple[str, str, str]]:
    """Returns ``(id, action, url)`` per agent."""
    done: list[tuple[str, str, str]] = []
    for entry in AGENTS:
        url = a2a_url(entry.id, entry.port, host)
        current = existing.get(entry.id)
        spec = load_spec(entry.id)
        card = spec.card(url)
        if current and str(current.get("agent_card_params", {}).get("url", "")).rstrip("/") == url:
            done.append((entry.id, "unchanged", url))
            continue
        if dry_run:
            done.append((entry.id, "would-put" if current else "would-post", url))
            continue
        try:
            if current:
                payload = {"agent_id": current["agent_id"], "agent_name": entry.id,
                           "agent_card_params": card}
                async with httpx.AsyncClient(base_url=gateway, timeout=60.0) as http:
                    response = await http.put(
                        f"/v1/agents/{current['agent_id']}", json=payload,
                        headers={"authorization": f"Bearer {admin}"},
                    )
                if response.status_code >= 400:
                    # No PATCH/PUT for agents on every gateway version: delete + re-create.
                    await _delete_agent(gateway, admin, current["agent_id"])
                    await ob.register_agent(
                        gateway, admin, name=entry.id, url=url,
                        protocol_version=protocol_version, card=card,
                    )
                    done.append((entry.id, "re-created", url))
                else:
                    done.append((entry.id, "updated", url))
            else:
                await ob.register_agent(
                    gateway, admin, name=entry.id, url=url,
                    protocol_version=protocol_version, card=card,
                )
                done.append((entry.id, "created", url))
        except Exception as exc:  # one bad agent must not stop the rest
            done.append((entry.id, f"FAILED: {exc}", url))
    return done


async def _delete_agent(gateway: str, admin: str, agent_id: str) -> None:
    async with httpx.AsyncClient(base_url=gateway, timeout=60.0) as http:
        await http.delete(f"/v1/agents/{agent_id}",
                          headers={"authorization": f"Bearer {admin}"})


async def register_mcp(
    gateway: str, admin: str, *, host: str, dry_run: bool,
    existing: dict[str, dict],
) -> list[tuple[str, str, str]]:
    done: list[tuple[str, str, str]] = []
    for entry in SERVERS:
        name, url = mcp_name(entry.id), mcp_url(entry.id, entry.port, host)
        current = existing.get(name)
        if current and str(current.get("url", "")).rstrip("/") == url.rstrip("/"):
            done.append((name, "unchanged", url))
            continue
        if dry_run:
            done.append((name, "would-update" if current else "would-create", url))
            continue
        body = {
            "server_name": name,
            "alias": name,
            "transport": "http",
            "url": url,
            "description": entry.description,
        }
        try:
            async with httpx.AsyncClient(base_url=gateway, timeout=60.0) as http:
                if current:
                    body["server_id"] = current["server_id"]
                    response = await http.put("/v1/mcp/server", json=body,
                                              headers={"authorization": f"Bearer {admin}"})
                else:
                    response = await http.post("/v1/mcp/server", json=body,
                                               headers={"authorization": f"Bearer {admin}"})
            if response.status_code >= 400:
                done.append((name, f"FAILED {response.status_code}: {response.text[:120]}", url))
            else:
                done.append((name, "updated" if current else "created", url))
        except Exception as exc:
            done.append((name, f"FAILED: {exc}", url))
    return done


async def grant(
    gateway: str, admin: str, virtual_key: str, *, team_id: str, dry_run: bool,
) -> dict[str, Any]:
    """Union the suite targets into team and key, then report what changed."""
    async with httpx.AsyncClient(base_url=gateway, timeout=60.0) as http:
        key_info = (await http.get("/key/info", params={"key": virtual_key},
                                   headers={"authorization": f"Bearer {admin}"})).json()["info"]
    team = team_id or str(key_info.get("team_id") or "")
    key_obj = key_info.get("object_permission") or {}

    wanted_agents = {a["agent_id"] for a in await ob.list_agents(gateway, admin)}
    wanted_servers = {s["server_name"] for s in await _servers(gateway, admin)}
    agents = sorted(set(key_obj.get("agents") or []) | wanted_agents)
    servers = sorted(set(key_obj.get("mcp_servers") or []) | wanted_servers)

    if dry_run:
        return {"team_id": team, "agents": len(agents), "mcp_servers": len(servers),
                "action": "would-update"}

    headers = {"authorization": f"Bearer {admin}", "content-type": "application/json"}
    async with httpx.AsyncClient(base_url=gateway, timeout=120.0, headers=headers) as http:
        if team:
            response = await http.post("/team/update", json={
                "team_id": team,
                "object_permission": {"agents": agents, "mcp_servers": servers},
            })
            if response.status_code >= 400:
                raise SystemExit(f"team grant failed: {response.text[:200]}")
        response = await http.post("/key/update", json={
            "key": virtual_key,
            "object_permission": {
                "agents": agents, "mcp_servers": servers,
                # Needed for semantic tool search, which the orchestrator relies on.
                "mcp_tool_search_enabled": True,
            },
        })
        if response.status_code >= 400:
            raise SystemExit(f"key grant failed: {response.text[:200]}")
    return {"team_id": team, "agents": len(agents), "mcp_servers": len(servers),
            "action": "updated"}


async def _servers(gateway: str, admin: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=gateway, timeout=60.0) as http:
        response = await http.get("/v1/mcp/server",
                                  headers={"authorization": f"Bearer {admin}"})
    return list(response.json())


async def verify(gateway: str, virtual_key: str) -> dict[str, Any]:
    """Ask the gateway what the *virtual key* can reach — the orchestrator's view."""
    headers = {"authorization": f"Bearer {virtual_key}"}
    async with httpx.AsyncClient(base_url=gateway, timeout=120.0, headers=headers) as http:
        agents = (await http.get("/v1/agents")).json()
        ok, bad = [], []
        for entry in SERVERS:
            name = mcp_name(entry.id)
            response = await http.get("/mcp-rest/tools/list", params={"server_id": name})
            tools = [t.get("name") for t in (response.json().get("tools") or [])] \
                if response.status_code < 400 else []
            # The underscore name must serve its own tools, not another server's.
            if tools:
                ok.append(f"{name}({len(tools)})")
            else:
                bad.append(f"{name}: {response.status_code}")
    return {
        "agents": len(agents),
        "agent_names": sorted(a.get("agent_name") for a in agents),
        "mcp_reachable": len(ok),
        "mcp_unreachable": bad,
    }


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    gateway = args.gateway or settings.litellm_base_url
    admin = args.admin_key or settings.litellm_admin_key
    virtual = args.virtual_key or settings.litellm_api_key
    if not virtual:
        print("LITELLM_API_KEY (virtual key) is required for verification", file=sys.stderr)
        return 2

    if not args.verify_only:
        if not admin:
            print("LITELLM_ADMIN_KEY or --admin-key is required to register", file=sys.stderr)
            return 2
        existing_agents, existing_servers = await _existing(gateway, admin)
        print(f"registry now: {len(existing_agents)} agents, {len(existing_servers)} MCP servers")

        a2a = await register_a2a(
            gateway, admin, host=args.a2a_host, protocol_version=args.protocol_version,
            dry_run=args.dry_run, existing=existing_agents,
        )
        mcp = await register_mcp(
            gateway, admin, host=args.mcp_host, dry_run=args.dry_run,
            existing=existing_servers,
        )
        for rows, label in ((a2a, "A2A"), (mcp, "MCP")):
            actions: dict[str, int] = {}
            for _, action, _ in rows:
                actions[action] = actions.get(action, 0) + 1
            print(f"{label}: " + ", ".join(f"{k}={v}" for k, v in sorted(actions.items())))
            for name, action, url in rows:
                if action.startswith("FAILED"):
                    print(f"  !! {name}: {action}", file=sys.stderr)

        if args.grant and not args.dry_run:
            result = await grant(gateway, admin, virtual, team_id=args.team_id,
                                 dry_run=args.dry_run)
            print(f"grant: {result['action']} team={result['team_id'] or '(none)'} "
                  f"agents={result['agents']} mcp_servers={result['mcp_servers']}")
        elif args.grant:
            print("grant: skipped (dry run)")

        if args.dry_run:
            print("dry run: nothing was written")
            return 0

    report = await verify(gateway, virtual)
    print(json.dumps(report, indent=2))
    return 0 if not report["mcp_unreachable"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="", help="gateway base URL (default: .env)")
    parser.add_argument("--admin-key", default="", help="gateway admin key (default: .env)")
    parser.add_argument("--virtual-key", default="", help="orchestrator key (default: .env)")
    parser.add_argument("--team-id", default="", help="team to grant (default: key's team)")
    parser.add_argument("--a2a-host", default=A2A_HOST,
                        help="host template for A2A cards: 'a2a-{id}' for compose, "
                             "'localhost' for a host-run suite")
    parser.add_argument("--mcp-host", default=MCP_HOST,
                        help="host template for MCP servers: 'mcp-{id}' for compose, "
                             "'host.docker.internal' for a host-run suite")
    parser.add_argument("--protocol-version", default="0.3",
                        help="A2A protocolVersion pinned on the card (suite speaks 0.3)")
    parser.add_argument("--grant", action="store_true", help="also update team and key grants")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--verify-only", action="store_true",
                        help="skip registration; only report what the virtual key sees")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
