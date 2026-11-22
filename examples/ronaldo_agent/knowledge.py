"""What the Ronaldo agent actually knows.

Fact base rather than a model call, so the agent is deterministic and free to run. Each
entry is a topic the card advertises. When a question is outside this base the agent says
so instead of guessing — that is the behaviour you want to see from an external agent your
orchestrator trusts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KNOWLEDGE_CUTOFF = "mid-2025"


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    keywords: tuple[str, ...]
    text: str


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="identity",
        title="Who he is",
        keywords=("who", "ronaldo", "identify", "introduce", "about", "summary", "overview"),
        text=(
            "Cristiano Ronaldo dos Santos Aveiro is a Portuguese professional footballer, "
            "widely regarded as one of the greatest players of all time. He is known for his "
            "goalscoring, athleticism, longevity at the top level, and for captaining Portugal "
            "to their first major international trophy."
        ),
    ),
    Topic(
        key="birth",
        title="Birth and background",
        keywords=("born", "birth", "birthday", "age", "where", "madeira", "funchal", "nationality", "portuguese"),
        text=(
            "He was born on 5 February 1985 in Funchal, on the island of Madeira, Portugal. "
            "He holds Portuguese nationality."
        ),
    ),
    Topic(
        key="early_life",
        title="Early life and family",
        keywords=("early", "childhood", "family", "father", "mother", "parents", "brother", "sister", "poor", "grew"),
        text=(
            "He grew up in a working-class family in Funchal as the youngest of four children, "
            "with older siblings Hugo, Elma and Catia. His father, Jose Dinis Aveiro, died in "
            "2005; his mother is Maria Dolores dos Santos Aveiro. He was named after Ronald "
            "Reagan, his father's favourite actor. He left Madeira as a teenager to join "
            "Sporting CP's academy in Lisbon."
        ),
    ),
    Topic(
        key="clubs",
        title="Club career",
        keywords=("club", "clubs", "career", "played", "play", "sporting", "united", "madrid", "juventus", "nassr", "transfer", "team"),
        text=(
            "Club career in order:\n"
            "1. Sporting CP (2002-2003) - his professional debut.\n"
            "2. Manchester United (2003-2009) - signed as a teenager; won three Premier League "
            "titles and the 2008 Champions League; first Ballon d'Or in 2008.\n"
            "3. Real Madrid (2009-2018) - signed for a then world-record fee; became the club's "
            "all-time leading goalscorer with 450 goals in 438 games; won four Champions Leagues "
            "and two La Liga titles.\n"
            "4. Juventus (2018-2021) - won two Serie A titles.\n"
            "5. Manchester United again (2021-2022).\n"
            "6. Al Nassr in the Saudi Pro League, which he joined in January 2023."
        ),
    ),
    Topic(
        key="portugal",
        title="Portugal national team",
        keywords=("portugal", "national", "country", "euro", "euros", "world cup", "nations league", "captain", "international", "caps"),
        text=(
            "He debuted for Portugal in 2003 and became captain. He won UEFA Euro 2016 and the "
            "inaugural UEFA Nations League in 2019, and holds the record for the most caps and "
            "the most goals in men's international football."
        ),
    ),
    Topic(
        key="records",
        title="Records",
        keywords=("record", "records", "most", "goals", "goal", "scorer", "scoring", "champions league", "history"),
        text=(
            "Notable records:\n"
            "- All-time leading goalscorer in men's international football.\n"
            "- Most appearances in men's international football.\n"
            "- All-time top scorer in the UEFA Champions League.\n"
            "- Most goals in a single Champions League season (17, in 2013-14).\n"
            "- Real Madrid's all-time leading goalscorer (450 goals)."
        ),
    ),
    Topic(
        key="awards",
        title="Awards",
        keywords=("award", "awards", "ballon", "trophy", "trophies", "honour", "honors", "golden boot", "best", "won"),
        text=(
            "He has won the Ballon d'Or five times (2008, 2013, 2014, 2016, 2017) and the "
            "European Golden Shoe four times, along with league titles in England, Spain and "
            "Italy and five Champions League titles."
        ),
    ),
    Topic(
        key="personal",
        title="Personal life",
        keywords=("personal", "wife", "partner", "girlfriend", "children", "kids", "son", "daughter", "georgina", "marry"),
        text=(
            "His partner is Georgina Rodriguez, and the couple have a large family including "
            "his son Cristiano Jr. In 2022 the couple announced the birth of twins, of whom one "
            "survived. Off the pitch he runs the CR7 brand, covering clothing, hotels and "
            "related ventures."
        ),
    ),
    Topic(
        key="business",
        title="Beyond football",
        keywords=("business", "brand", "cr7", "hotel", "invest", "endorsement", "instagram", "social"),
        text=(
            "Outside football he has built the CR7 brand across clothing, footwear, hotels and "
            "a museum in Madeira, and is one of the most followed people on social media."
        ),
    ),
)

_STOP = frozenset(
    "a an the and or of in on at to for from with about is are was were be been do does did "
    "what who whom whose when where why how tell me give please his he him their there this "
    "that these those it its as by i you we they".split()
)


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", text.lower()) if word not in _STOP}


def match_topics(query: str) -> list[Topic]:
    """Score topics by keyword hits, best first."""
    words = _tokens(query)
    scored: list[tuple[int, int, Topic]] = []
    for index, topic in enumerate(TOPICS):
        hits = sum(1 for keyword in topic.keywords if keyword in words)
        # "ronaldo" alone matches identity; do not let that drown out a specific ask.
        if hits:
            scored.append((hits, -index, topic))
    scored.sort(reverse=True)
    return [topic for _, _, topic in scored]


_BIOGRAPHY_TRIGGERS = ("biography", "bio ", " life story", "background", "about him", "about ronaldo")


def _by_key(key: str) -> Topic:
    return next(topic for topic in TOPICS if topic.key == key)


def compose_biography() -> str:
    """A real biography, assembled from the fact base in reading order."""
    order = ("identity", "birth", "early_life", "clubs", "portugal", "records", "awards", "personal")
    blocks = [f"{_by_key(key).title}\n{_by_key(key).text}" for key in order]
    return "Cristiano Ronaldo — biography\n\n" + "\n\n".join(blocks) + (
        f"\n\n(Knowledge current to {KNOWLEDGE_CUTOFF}.)"
    )


def answer(query: str) -> str:
    """Answer from the fact base, or say plainly that the question is out of scope."""
    query = (query or "").strip()
    if not query:
        return "Ask me about Cristiano Ronaldo's biography, career or records."

    lowered = f" {query.lower()} "
    if any(trigger in lowered for trigger in _BIOGRAPHY_TRIGGERS):
        return compose_biography()

    matched = match_topics(query)
    if not matched:
        return (
            "I can only answer questions about Cristiano Ronaldo's biography, club and "
            "international career, records and awards. "
            f"Try something like: 'who is Cristiano Ronaldo?' or 'which clubs has he played for?' "
            f"(My knowledge is current to {KNOWLEDGE_CUTOFF}.)"
        )

    # One focused answer when there is a clear winner, otherwise a short briefing.
    top_hits = len(matched)
    if top_hits == 1:
        topic = matched[0]
        return f"{topic.title}\n\n{topic.text}"

    primary = matched[0]
    body = f"{primary.title}\n\n{primary.text}"
    extras = [topic for topic in matched[1:] if topic.key not in {"identity"}][:2]
    if extras:
        body += "\n\n" + "\n\n".join(f"{topic.title}\n{topic.text}" for topic in extras)
    return body.rstrip() + f"\n\n(Knowledge current to {KNOWLEDGE_CUTOFF}.)"
