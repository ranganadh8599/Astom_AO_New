"""Direct answers for greetings, thanks and questions about the assistant.

The orchestrator is a router: it picks a target and merges the results. A greeting has no
target, so routing produces nothing and declining says "nothing covers that" — wrong for
"hi", and wrong for "what can you do?", which is a legitimate question about the system.

The pattern is borrowed from `multi_agent_system` in this workspace, whose router has an
`ANSWER` route for "greetings, thanks, and basic acknowledgments" and "system capabilities
and features", separate from its knowledge route.

Two deliberate constraints:

* **A fixed set of responses, not a model call.** A greeting costs nothing and behaves
  identically every time. A model could produce a nicer sentence, but it would also be a
  billable call on the most frequent message a chat front end sends.
* **No mutation, no routing.** This never invokes a target and never answers anything that
  needs business data — anything unrecognised falls through to normal coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Greetings and acknowledgements. Matched against the whole message (after trimming
# punctuation), so "hi" matches but "hi, what is the leave policy?" does not.
_GREETING_RE = re.compile(
    r"^(?:hi|hii+|hey|hello|helo|yo|good\s+(?:morning|afternoon|evening|day)|"
    r"greetings|howdy|namaste)$"
)
# "thanks", "thanks, that helps", "thank you!", "great, thanks", "that helped a lot".
# Kept anchored so "thanks, and what are the incidents in Lyon?" does not match.
_THANKS_RE = re.compile(
    r"^(?:"
    r"(?:thanks?|thank\s+you|thx|ty|cheers|much\s+appreciated)"
    r"(?:\s*,?\s*(?:that|this|it|you|a\s+lot|so\s+much)?"
    r"\s*(?:helps?|helped|works?|worked|is\s+helpful|was\s+helpful)?)?"
    r"|"
    r"(?:that|this|it)\s+(?:helps?|helped|works?|worked|is\s+helpful|was\s+helpful)"
    r"(?:\s*,?\s*(?:thanks?|thank\s+you)?)?"
    r"|"
    r"(?:great|nice|perfect|awesome|cool|ok|okay|got\s+it|understood)"
    r"(?:\s*,?\s*(?:thanks?|thank\s+you)?)?"
    r")$"
)
_CAPABILITIES_RE = re.compile(
    r"(?:what\s+can\s+you\s+do|what\s+do\s+you\s+do|what\s+are\s+you|who\s+are\s+you|"
    r"what\s+is\s+this|how\s+does\s+this\s+work|what\s+can\s+i\s+ask|"
    r"what\s+topics|help)$"
)
# An imperative that asks for output: "write me a poem", "translate this", "list the
# open incidents". Such a message is never social, whatever a model labels it.
_REQUEST_RE = re.compile(
    r"\b(?:write|generate|draft|compose|translate|calculate|compute|summari[sz]e|"
    r"explain|describe|list|show|find|search|look\s*up|compare|convert|produce|"
    r"create|make|give\s+me|tell\s+me|recommend|suggest|how\s+(?:do|can|should|many|much))\b",
    re.IGNORECASE,
)
_PUNCT = " \t\n\r.,!?;:'\"()[]-—–"

# A display name is used in a greeting, so it must look like a name rather than an
# identifier: shared-key mode sets `name` to the email or user id when no name is sent,
# and greeting someone as "6b00d8662f63e48e5b1a9b26" is worse than not naming them.
_NAME_RE = re.compile(r"^[^\W\d_][\w'’.-]*(?:\s+[^\W\d_][\w'’.-]*){0,3}$", re.UNICODE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def display_name(raw: str, *, max_chars: int = 40) -> str:
    """First name from a display name, or ``""`` when there is nothing usable.

    Conservative on purpose:

    * an email or an opaque id is not a name — returns ``""``
    * only the first token is used, so "Orch Tester" greets as "Orch"
    * anything with digits, punctuation soup or excessive length is rejected

    Personalisation is a nicety; greeting someone by their user id or email local-part
    is worse than a plain "Hello", so the fallback is always silence.
    """
    candidate = " ".join((raw or "").split()).strip(_PUNCT)
    if not candidate or len(candidate) > max_chars:
        return ""
    if _EMAIL_RE.match(candidate):
        return ""
    # Strip a "Last, First" form to the first given name.
    first = candidate.split(",")[-1].strip().split(" ")[0].strip(_PUNCT)
    if not first or len(first) < 2 or any(ch.isdigit() for ch in first):
        return ""
    if not _NAME_RE.match(first):
        return ""
    return first


@dataclass(frozen=True)
class SmallTalk:
    kind: str  # greeting | thanks | capabilities
    reply: str


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding punctuation."""
    return " ".join((text or "").lower().split()).strip(_PUNCT)


# A leading greeting followed by a real request: "hi, what is our leave policy?".
# The greeting is noise for the gate and the planner, which then judge the whole message
# as smalltalk-plus-question and often conclude nothing covers it.
_LEADING_GREETING_RE = re.compile(
    r"^(?:hi|hii+|hey|hello|helo|yo|good\s+(?:morning|afternoon|evening|day)|"
    r"greetings|howdy)"
    r"[\s,.!—-]+",
    re.IGNORECASE,
)


def strip_leading_greeting(text: str) -> str:
    """Remove a leading greeting, leaving the actual request.

    Returns the original text when nothing follows the greeting — "hi" alone is
    smalltalk, handled elsewhere, and stripping it would leave an empty query.

    Also returns the original when what follows is *not* a request. Measured failure:
    "good day to you all" was stripped to "to you all", which is neither a greeting nor
    a question, so it reached retrieval and the gate as nonsense.
    """
    original = text or ""
    stripped = _LEADING_GREETING_RE.sub("", original.strip(), count=1).strip()
    if not stripped:
        return original
    if "?" not in stripped and not _REQUEST_RE.search(_normalise(stripped)):
        # The greeting was the whole message ("good day to you all"): leave it intact so
        # the conversational path can answer it.
        return original
    return stripped


def neutral_reply(*, user_name: str = "", capabilities_reply: str = "") -> SmallTalk:
    """The reply used when the *gate*, not the heuristics, calls a message smalltalk.

    Same wording as ``detect`` for a greeting, so the user cannot tell which path ran.
    """
    name = display_name(user_name)
    reply = (
        f"Hello {name}. I can route your question to the right internal agent or tool — "
        "what would you like to know?"
        if name
        else (
            "Hello. I can route your question to the right internal agent or tool — "
            "what would you like to know?"
        )
    )
    return SmallTalk(kind="greeting", reply=reply)


def looks_like_request(text: str) -> bool:
    """Whether the message asks for an answer or output rather than being social.

    Exists because a model labelling a message "smalltalk" is not reliable for content
    requests: "write me a short poem" and "translate good morning into Japanese" were
    both labelled that way. Answering them with a greeting silently drops the request,
    which is worse than declining, so an imperative verb or a question mark overrides
    the label.

    A question *about the assistant* keeps its smalltalk outcome even though it ends in
    "?" — "what can you do?" must still be answered, not declined.
    """
    normalised = _normalise(text)
    if _CAPABILITIES_RE.match(normalised):
        return False
    return "?" in (text or "") or bool(_REQUEST_RE.search(normalised))


def detect(
    text: str,
    *,
    capabilities_reply: str = "",
    user_name: str = "",
) -> SmallTalk | None:
    """Return a canned reply, or ``None`` when the message needs real routing.

    Deliberately conservative: a message that mixes smalltalk with a question
    ("hi, what is our leave policy?") is **not** smalltalk, because answering the
    greeting alone would drop the question. The trailing-question check below is what
    enforces that.

    ``user_name`` personalises the greeting when it yields a usable display name; an
    email, an opaque id or an empty value simply produces the neutral wording.
    """
    normalised = _normalise(text)
    if not normalised or len(normalised) > 60:
        return None

    # Capabilities questions are questions by nature ("what can you do?"), so they are
    # matched before the question-mark guard below.
    if _CAPABILITIES_RE.match(normalised):
        return SmallTalk(
            kind="capabilities",
            reply=capabilities_reply
            or (
                "I route questions to the right internal agent or tool. Ask about a "
                "topic and I will find the best source for it. I am read-only: I answer "
                "questions but never change anything."
            ),
        )

    name = display_name(user_name)

    # A greeting followed by a question is a question. Answering only the greeting would
    # silently drop the question, which is worse than declining.
    if "?" in (text or ""):
        return None

    if _THANKS_RE.match(normalised):
        return SmallTalk(
            kind="thanks",
            reply=(
                f"Glad that helped, {name}. Ask me anything else."
                if name
                else "Glad that helped. Ask me anything else."
            ),
        )
    if _GREETING_RE.match(normalised):
        reply = (
            f"Hello {name}. I can route your question to the right internal agent or "
            "tool — what would you like to know?"
            if name
            else (
                "Hello. I can route your question to the right internal agent or tool — "
                "what would you like to know?"
            )
        )
        return SmallTalk(kind="greeting", reply=reply)
    return None
