"""Shared fixtures: a fake LiteLLM gateway with no network access."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orchestrator.config import Settings
from orchestrator.gateway import LiteLLMGateway

AGENTS = [
    {
        "agent_id": "hr-1",
        "agent_name": "hr-policy-agent",
        "description": "Answers HR policy, leave and benefits questions",
        "agent_card_params": {
            "name": "hr-policy-agent",
            "description": "Answers HR policy, leave and benefits questions",
            "url": "http://hr.internal:8080",
            "version": "1.0.0",
            "protocolVersion": "1.0",
            "skills": [
                {"id": "leave", "name": "Leave policy", "description": "annual and sick leave", "tags": ["hr"]}
            ],
        },
    },
    {
        "agent_id": "fin-1",
        "agent_name": "finance-agent",
        "description": "Expense reimbursement and invoice questions",
        "agent_card_params": {
            "name": "finance-agent",
            "description": "Expense reimbursement and invoice questions",
            "url": "http://finance.internal:8080",
            "version": "1.0.0",
            "protocolVersion": "1.0",
            "skills": [
                {"id": "expense", "name": "Expenses", "description": "reimbursement status", "tags": ["finance"]}
            ],
        },
    },
    {
        "agent_id": "it-1",
        "agent_name": "it-support-agent",
        "description": "Laptop provisioning and VPN access",
        "agent_card_params": {
            "name": "it-support-agent",
            "description": "Laptop provisioning and VPN access",
            "url": "http://it.internal:8080",
            "version": "1.0.0",
            "protocolVersion": "1.0",
            "skills": [{"id": "vpn", "name": "VPN", "description": "vpn access requests", "tags": ["it"]}],
        },
    },
]

REPLIES = {
    "hr-1": "You get 24 days of annual leave.",
    "fin-1": "Your expense claim is approved for 1200 INR.",
    "it-1": "VPN access is granted for 30 days.",
}

MCP_SERVERS = [
    {"server_id": "orders", "server_name": "orders", "url": "http://orders.mcp"},
]

MCP_TOOLS = {
    "orders": [
        {
            "name": "get_order_status",
            "description": "Look up the shipping status of a customer order",
            "inputSchema": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        }
    ]
}

MCP_REPLIES = {"get_order_status": "Order ord-1 is shipped and arriving tomorrow."}


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "litellm_base_url": "http://gateway.test",
        "litellm_api_key": "sk-orchestrator",
        # Routing is the planner model's job, so every test drives a planner.
        "planner_model": "test/planner",
        "max_agents_per_request": 3,
        # MCP is opt-in in tests so the A2A-only cases stay unchanged.
        "protocols": ("a2a",),
        # Query rewriting adds a model call; the tests about it opt in explicitly.
        "query_rewrite_enabled": False,
        "search_retry_backoff_s": 0.0,
    }
    base.update(overrides)
    return Settings(**base)


# The planner's view of the fixture world. Keys are the marker used to recognise a
# request; the value is the JSON the fake planner returns.
PLANNER_ROUTES: list[tuple[str, dict[str, Any]]] = [
    (
        "leave",
        {
            "intent": "read",
            "reason": "asking about leave policy",
            "tasks": [
                {
                    "agent": "hr-policy-agent",
                    "instruction": "How many annual leave days does the user get?",
                }
            ],
        },
    ),
    (
        "expense",
        {
            "intent": "read",
            "reason": "checking a reimbursement",
            "tasks": [
                {"agent": "finance-agent", "instruction": "Is the expense approved?"}
            ],
        },
    ),
    (
        "vpn",
        {
            "intent": "read",
            "reason": "asking about VPN access",
            "tasks": [{"agent": "it-support-agent", "instruction": "How do I get VPN access?"}],
        },
    ),
    (
        "laptop",
        {
            "intent": "read",
            "reason": "asking about laptop provisioning",
            "tasks": [{"agent": "it-support-agent", "instruction": "How do I get a laptop?"}],
        },
    ),
    (
        "order",
        {
            "intent": "read",
            "reason": "checking an order",
            "tasks": [
                {
                    "agent": "orders-get_order_status",
                    "instruction": "Look up the order",
                    "arguments": {"order_id": "ord-1"},
                }
            ],
        },
    ),
    (
        "who is ronaldo",
        {
            "intent": "read",
            "reason": "biography question",
            "tasks": [{"agent": "hr-policy-agent", "instruction": "Who is Ronaldo?"}],
        },
    ),
]


class FakeGateway:
    """Records every request so tests can assert on headers, protocol and fan-out."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_agents: set[str] = set()
        self.fail_mcp: set[str] = set()
        self.mcp_discovery_status: int = 200
        self.planner_prompts: list[str] = []
        # Overrides for planner behaviour in specific tests.
        self.planner_fails: bool = False
        self.planner_fail_times: int = 0
        self.planner_429_times: int = 0
        self.planner_raw: str | None = None
        self.default_mutation: bool = False
        # Retrieval surface: both default to "not configured", matching a gateway with
        # no embedding model and a key without mcp_tool_search_enabled.
        self.agent_search_enabled: bool = False
        self.mcp_tool_search_enabled: bool = False
        # Ranked results to return for agent search: {agent_id: search_score}.
        self.agent_scores: dict[str, float] = {"hr-1": 0.52, "fin-1": 0.11, "it-1": 0.09}
        # When True, score by token overlap instead of `agent_scores`.
        self.rank_by_overlap: bool = False
        # Coverage gate behaviour.
        self.gate_prompts: list[str] = []
        self.gate_no_match: bool = False
        self.gate_fails: bool = False
        self.gate_raw: str | None = None
        # Query builder behaviour: the JSON the "model" answers with (None = echo the
        # user message back as the only query), and whether the call fails.
        self.rewrite_prompts: list[str] = []
        self.rewrite_raw: str | None = None
        self.rewrite_fails: bool = False
        # Search failures to inject: this many 500s from agent search / mcp_tool_search
        # before it starts answering normally.
        self.agent_search_errors: int = 0
        self.agent_search_queries: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if request.method == "GET" and path == "/v1/agents":
            ranked = request.url.params.get("query")
            if ranked:
                self.agent_search_queries.append(ranked)
                if self.agent_search_errors > 0:
                    self.agent_search_errors -= 1
                    return httpx.Response(500, json={"error": "embedding backend hiccup"})
                if not self.agent_search_enabled:
                    return httpx.Response(
                        400,
                        json={"detail": {"error": "agent_search_not_configured",
                                         "message": "agent search needs litellm_settings."
                                                    "agent_search_embedding_model set"}},
                    )
                top = int(request.url.params.get("top_k") or 8)
                return httpx.Response(200, json=self._ranked_agents(ranked)[:top])
            return httpx.Response(200, json=AGENTS)

        if request.method == "GET" and path.startswith("/a2a/") and path.endswith(
            "/.well-known/agent-card.json"
        ):
            agent_id = path.split("/")[2]
            for agent in AGENTS:
                if agent["agent_id"] == agent_id:
                    return httpx.Response(200, json=agent["agent_card_params"])
            return httpx.Response(404, json={"error": "not found"})

        if request.method == "POST" and path.startswith("/a2a/"):
            agent_id = path.split("/")[2]
            agent = next((a for a in AGENTS if a["agent_id"] == agent_id), None)
            names = {agent_id, agent["agent_name"]} if agent else {agent_id}
            if names & self.fail_agents:
                return httpx.Response(500, json={"error": "agent exploded"})
            body = json.loads(request.content or b"{}")
            text = json.dumps(body)
            assert "message" in text
            return httpx.Response(
                200,
                json={"result": {"parts": [{"kind": "text", "text": REPLIES[agent_id]}]}},
            )

        # -- MCP surface exposed by the gateway ---------------------------
        if request.method == "GET" and path in ("/v1/mcp/server", "/mcp-rest/tools/list"):
            if self.mcp_discovery_status != 200:
                return httpx.Response(
                    self.mcp_discovery_status,
                    json={"error": {"message": "The key is not allowed to access any MCP servers."}},
                )
            if path == "/v1/mcp/server":
                return httpx.Response(200, json={"data": MCP_SERVERS})

        if request.method == "GET" and path == "/mcp-rest/tools/list":
            server_id = request.url.params.get("server_id") or ""
            if server_id:
                return httpx.Response(200, json={"tools": MCP_TOOLS.get(server_id, [])})
            return httpx.Response(
                200,
                json={
                    "tools": [
                        {**tool, "mcp_info": {"server_id": server, "server_name": server}}
                        for server, tools in MCP_TOOLS.items()
                        for tool in tools
                    ]
                },
            )

        if request.method == "POST" and path == "/mcp-rest/tools/call":
            body = json.loads(request.content or b"{}")
            name = body.get("name", "")

            if name == "mcp_tool_search":
                if not self.mcp_tool_search_enabled:
                    return httpx.Response(
                        403,
                        json={"detail": {"error": "forbidden",
                                         "message": "mcp_tool_search requires "
                                                    "mcp_tool_search_enabled on the key"}},
                    )
                query = str((body.get("arguments") or {}).get("query", "")).lower()
                top = int((body.get("arguments") or {}).get("top_k") or 5)
                hits = []
                for server, tools in MCP_TOOLS.items():
                    for tool in tools:
                        words = f"{tool['name']} {tool['description']}".lower()
                        if any(token in words for token in query.split()):
                            hits.append(
                                {
                                    **tool,
                                    # search returns the prefixed name
                                    "name": f"{server}-{tool['name']}",
                                    "score": 0.42,
                                }
                            )
                return httpx.Response(
                    200,
                    json={"content": [{"type": "text", "text": json.dumps(hits[:top])}]},
                )

            if name in self.fail_mcp:
                return httpx.Response(200, json={"content": [{"type": "text", "text": "tool failed"}], "isError": True})
            return httpx.Response(
                200,
                json={"content": [{"type": "text", "text": MCP_REPLIES.get(name, "")}]},
            )

        if request.method == "POST" and path == "/v1/chat/completions":
            body = json.loads(request.content or b"{}")
            messages = body.get("messages", [])
            system = next(
                (str(m.get("content", "")) for m in messages if m.get("role") == "system"), ""
            )
            prompt = "\n".join(str(m.get("content", "")) for m in messages)

            if "You turn a user's message into search queries" in system:
                self.rewrite_prompts.append(prompt)
                if self.rewrite_fails:
                    return httpx.Response(500, json={"error": "rewrite model down"})
                content = self.rewrite_raw
                if content is None:
                    user = next(
                        (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
                        "",
                    )
                    message = user.split("User message:\n", 1)[-1]
                    content = json.dumps({"queries": [message]})
                return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

            if "You triage a read-only enterprise assistant" in system:
                return httpx.Response(200, json=self._gate_response(prompt))

            planner = self._planner_response(body, prompt)
            # A simulated rate limit returns a Response instead of a payload so the
            # handler can emit the real status code.
            if isinstance(planner, httpx.Response):
                return planner
            return httpx.Response(200, json=planner)

        return httpx.Response(404, json={"error": f"unhandled {request.method} {path}"})

    def _ranked_agents(self, query: str) -> list[dict[str, Any]]:
        """Agent search result: the same rows plus the relevance the gateway adds."""
        ranked = []
        for agent in AGENTS:
            score = self.agent_scores.get(agent["agent_id"], 0.0)
            if self.rank_by_overlap:
                words = f"{agent['agent_name']} {agent['description']}".lower()
                score = 0.5 if any(t in words for t in query.lower().split()) else 0.02
            ranked.append({**agent, "search_score": score})
        return sorted(ranked, key=lambda a: -a["search_score"])

    def _gate_response(self, prompt: str) -> dict[str, Any]:
        """Stand in for the coverage gate.

        Default: affirm the message and name the agents the planner route implies. That
        keeps existing tests about routing working while still exercising the gate.
        """
        message = self._user_message(prompt)
        self.gate_prompts.append(prompt)

        if self.gate_fails:
            return {"choices": [{"message": {"content": "not json"}}]}

        if self.gate_raw is not None:
            return {"choices": [{"message": {"content": self.gate_raw}}]}

        if self.gate_no_match:
            content = json.dumps(
                {
                    "intent": "read",
                    "can_answer": False,
                    "targets": [],
                    "reason": "nothing in the registry covers this",
                    "confidence": 0.9,
                }
            )
            return {"choices": [{"message": {"content": content}}]}

        if self.default_mutation:
            content = json.dumps(
                {
                    "intent": "mutation",
                    "can_answer": False,
                    "targets": [],
                    "reason": "asks to change something",
                    "confidence": 0.9,
                }
            )
            return {"choices": [{"message": {"content": content}}]}

        names = []
        for marker, decision in PLANNER_ROUTES:
            if marker in message:
                names.extend(task["agent"] for task in decision["tasks"])

        content = json.dumps(
            {
                "intent": "read",
                "can_answer": bool(names),
                "targets": names,
                "reason": "covers the request" if names else "nothing covers this",
                "confidence": 0.85 if names else 0.8,
            }
        )
        return {"choices": [{"message": {"content": content}}]}

    def _planner_response(self, body: dict[str, Any], prompt: str) -> dict[str, Any]:
        """Stand in for the planner model.

        Mirrors the real contract: one JSON object carrying both the intent and the task
        list. Matching is confined to the *user message* section, because target
        descriptions also contain words like "expense" and "VPN".
        """
        self.planner_prompts.append(prompt)
        message = self._user_message(prompt)

        # Rate-limit simulation: respond 429 a bounded number of times, then behave.
        if self.planner_429_times > 0:
            self.planner_429_times -= 1
            return httpx.Response(429, json={"error": {"message": "rate limited"}})

        # Fail a bounded number of times, then behave normally — used to prove the
        # one-retry-on-unusable-reply path without failing the whole turn.
        if self.planner_fail_times > 0:
            self.planner_fail_times -= 1
            return {"choices": [{"message": {"content": "not json"}}]}

        if self.planner_fails:
            return {"choices": [{"message": {"content": "not json"}}]}

        if self.planner_raw is not None:
            return {"choices": [{"message": {"content": self.planner_raw}}]}

        if self.default_mutation:
            return self._decision("mutation", "asks to change something", [])

        tasks: list[dict[str, Any]] = []
        reasons: list[str] = []
        for marker, decision in PLANNER_ROUTES:
            if marker in message:
                tasks.extend(decision["tasks"])
                reasons.append(decision["reason"])

        if tasks:
            return self._decision("read", "; ".join(reasons), tasks)
        return self._decision("read", "nothing fits", [])

    @staticmethod
    def _user_message(prompt: str) -> str:
        """Extract only the user's message from a planner prompt."""
        marker = "User message:"
        if marker in prompt:
            prompt = prompt.split(marker, 1)[1]
        for stop in ("Recent conversation:", "Registered targets:"):
            if stop in prompt:
                prompt = prompt.split(stop, 1)[0]
        return prompt.strip().lower()

    @staticmethod
    def _decision(intent: str, reason: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"intent": intent, "reason": reason, "tasks": tasks}
                        )
                    }
                }
            ]
        }

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://gateway.test",
            transport=httpx.MockTransport(self.handler),
        )


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


def tool_calls(fake_gateway: FakeGateway) -> list[httpx.Request]:
    """Requests that actually invoke an MCP tool (not the retrieval probe)."""
    calls = []
    for request in fake_gateway.requests:
        if request.method != "POST" or request.url.path != "/mcp-rest/tools/call":
            continue
        body = json.loads(request.content or b"{}")
        if body.get("name") != "mcp_tool_search":
            calls.append(request)
    return calls


def search_calls(fake_gateway: FakeGateway) -> list[httpx.Request]:
    """Requests that asked the gateway to rank tools."""
    calls = []
    for request in fake_gateway.requests:
        if request.method != "POST" or request.url.path != "/mcp-rest/tools/call":
            continue
        body = json.loads(request.content or b"{}")
        if body.get("name") == "mcp_tool_search":
            calls.append(request)
    return calls


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def gateway(settings: Settings, fake_gateway: FakeGateway) -> LiteLLMGateway:
    return LiteLLMGateway(settings, client=fake_gateway.client())
