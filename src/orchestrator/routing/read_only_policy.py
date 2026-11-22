"""Read-only policy.

The orchestrator answers questions. It cannot create, change, delete or approve anything,
and it deliberately has **no human-in-the-loop path**: no interrupt, no approval queue, no
resumable pending change.

Intent classification is the planner model's job, not this module's. The planner returns
``intent: "read" | "mutation"`` alongside the task list, and a ``mutation`` verdict ends
the turn with the message below.

Why it is safe to let a model classify:

* the structural guarantee is capability, not classification — only read-only agents and
  tools are registered on the gateway, so a permissive verdict still has nothing to
  invoke;
* this module holds no detection logic at all, so there is no pattern list to bypass and
  equally no pattern list to drift out of date.

If you later register a capability that *can* write, add a deterministic veto in front of
execution rather than trusting the classifier alone.
"""

from __future__ import annotations

from orchestrator.config import Settings

INTENT_READ = "read"
INTENT_MUTATION = "mutation"


def is_mutation(intent: str) -> bool:
    return (intent or "").strip().lower() == INTENT_MUTATION


def denial_message(settings: Settings, reason: str = "") -> str:
    """Compose the refusal shown to the user."""
    message = settings.read_only_denial_message.strip()
    reason = " ".join((reason or "").split())
    if reason and reason.lower() not in message.lower():
        message = f"{message}\n\nWhy: {reason}"
    return message
