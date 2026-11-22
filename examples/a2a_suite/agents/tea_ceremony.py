"""Japanese tea ceremony agent: procedure, utensils and seasonality."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "tea-ceremony",
    skills=(
        Skill(
            id="procedure",
            name="Temae and guest etiquette",
            description=(
                "The order of a tea procedure, entering and leaving, and how a guest receives "
                "and drinks."
            ),
            tags=("temae", "etiquette", "procedure"),
            keywords=(
                "temae", "procedure", "etiquette", "guest", "bow", "enter", "entrance",
                "sit", "tatami", "drink", "bowl", "order", "clean", "fold", "fukusa",
                "chanoyu", "ceremony",
            ),
            text=(
                "A chakai guest enters on the knees, admires the alcove and hearth, and bows to "
                "the next guest before sitting. The host purifies the utensils, prepares the "
                "tea and presents the bowl with the front turned toward the guest; the guest "
                "bows, lifts the bowl, turns it so the front faces away, drinks in the last "
                "sip, wipes the rim and turns it back. Guests then admire the bowl, and the "
                "host cleans the implements in view."
            ),
        ),
        Skill(
            id="utensils",
            name="Utensils",
            description=(
                "Chawan, chasen, chashaku, natsume and fukusa, and what each is for."
            ),
            tags=("chawan", "chasen", "utensils"),
            keywords=(
                "chawan", "bowl", "chasen", "whisk", "chashaku", "scoop", "natsume", "caddy",
                "fukusa", "cloth", "chakin", "kensui", "hishaku", "ladle", "utensil",
                "utensils", "mizusashi",
            ),
            text=(
                "The chawan is the tea bowl and the piece guests handle most carefully. The "
                "chasen is the bamboo whisk, with 80 to 120 tines for usucha and fewer for "
                "koicha; the chashaku is the bamboo scoop. The natsume holds usucha and the "
                "chaire holds koicha. The fukusa is the silk cloth used to purify the caddy and "
                "scoop, and the chakin wipes the bowl. The kensui receives rinse water and the "
                "hishaku is the bamboo ladle."
            ),
        ),
        Skill(
            id="season",
            name="Seasonality",
            description=(
                "Ro and furo hearths, seasonal flowers and the sweets served with tea."
            ),
            tags=("ro", "furo", "season"),
            keywords=(
                "season", "seasonal", "ro", "furo", "hearth", "brazier", "summer", "winter",
                "may", "october", "flower", "flowers", "chabana", "wagashi", "sweet",
                "sweets", "kigo", "theme",
            ),
            text=(
                "The furo (portable brazier) is used from May to October and the sunken ro "
                "hearth from November to April, changing where the kettle sits and which "
                "utensils are appropriate. Chabana, the tea flower, is a single seasonal bloom "
                "or branch arranged as if still growing. Wagashi are chosen to echo the season "
                "or the scroll's theme, and guests eat the sweet before drinking usucha."
            ),
        ),
    ),
)
