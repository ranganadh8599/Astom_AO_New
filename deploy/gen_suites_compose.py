"""Generate ``docker-compose.suites.yml`` from the two example catalogues.

The compose file is data, not code: 40 services that differ only by module, port and
advertised URL. Writing them by hand invites drift from ``catalog.py`` (a renamed agent, a
shifted port), and the failure mode is subtle — the container starts under a name the
gateway was never told about. So the catalogues are the single source of truth and this
script renders the file.

    python deploy/gen_suites_compose.py            # write docker-compose.suites.yml
    python deploy/gen_suites_compose.py --check    # exit 1 if the file is stale

``--check`` is what CI should run: it re-renders in memory and compares, so an agent added
to the catalogue without regenerating the compose file fails the build instead of silently
never being deployed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "examples")]

from a2a_suite.catalog import AGENTS  # noqa: E402
from mcp_suite.catalog import SERVERS  # noqa: E402

OUTPUT = ROOT / "docker-compose.suites.yml"
IMAGE = "a2a-examples:0.1.0"

HEADER = """\
# GENERATED FILE — do not edit by hand.
# Regenerate with:  python deploy/gen_suites_compose.py
#
# Every A2A agent (9110-9129) and MCP server (9301-9320) from examples/*/catalog.py as
# its own container. One image, 40 services, one process each.
#
#   docker build -f deploy/Dockerfile.examples -t {image} .
#   docker compose -f docker-compose.suites.yml up -d
#   .\\.venv\\Scripts\\python.exe deploy/register_examples.py --grant
#
# The gateway reaches a service by NAME on the shared network (the same network the
# gateway's own compose project created), which is why each A2A card advertises
# ``http://a2a-<id>:<port>`` and each MCP server is registered as
# ``http://mcp-<id>:<port>/mcp``. A card that advertised localhost would be unreachable
# from the gateway — the classic "works locally, 500s in the gateway" failure.
#
# Nothing is published to the host by default: the gateway dials the service name, and 40
# published ports would collide with the host-run suites. To debug one service from the
# host, add a ports mapping under it, e.g. ``ports: ["9110:9110"]``.

name: a2a-suites

x-suite: &suite
  image: ${{SUITES_IMAGE:-{image}}}
  build:
    context: .
    dockerfile: deploy/Dockerfile.examples
  restart: unless-stopped
  # The suites never need to write to disk or escalate.
  security_opt:
    - no-new-privileges:true
  networks:
    - default
    - gateway

services:
"""

FOOTER = """
networks:
  default:
  # The network the LiteLLM gateway already created. `external` means compose expects it to
  # exist and will not create or delete it. Verify with: docker network ls
  gateway:
    external: true
    name: ${GATEWAY_NETWORK:-litellm-gateway_default}
"""


def _service(service: str, command: list[str], kind: str, port: int) -> str:
    parts = "".join(f'      - "{part}"\n' for part in command[2:])
    return (
        f"  {service}:\n"
        "    <<: *suite\n"
        "    command:\n"
        '      - "python"\n'
        '      - "-m"\n'
        f"{parts}"
        "    environment:\n"
        f"      SUITE_KIND: {kind}\n"
        f'      PORT: "{port}"\n'
    )


def render() -> str:
    chunks = [HEADER.format(image=IMAGE)]
    for entry in AGENTS:
        service = f"a2a-{entry.id}"
        # The card must advertise the address the GATEWAY resolves, not localhost.
        url = f"http://{service}:{entry.port}"
        command = [
            "python", "-m", "a2a_suite.server",
            "--agent", entry.id,
            "--port", str(entry.port),
            "--url", url,
        ]
        chunks.append(_service(service, command, "a2a", entry.port))

    for entry in SERVERS:
        service = f"mcp-{entry.id}"
        module = f"mcp_suite.servers.{entry.id.replace('-', '_')}"
        command = ["python", "-m", module, "--port", str(entry.port)]
        chunks.append(_service(service, command, "mcp", entry.port))

    chunks.append(FOOTER)
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args()

    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != rendered:
            print(f"{OUTPUT.name} is stale: run python deploy/gen_suites_compose.py",
                  file=sys.stderr)
            return 1
        print(f"{OUTPUT.name} is up to date ({len(AGENTS) + len(SERVERS)} services)")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.name}: {len(AGENTS)} A2A agents + {len(SERVERS)} MCP servers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
