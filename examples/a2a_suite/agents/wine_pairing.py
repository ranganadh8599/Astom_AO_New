"""Wine pairing agent: principles, whites and reds."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "wine-pairing",
    skills=(
        Skill(
            id="principles",
            name="Pairing principles",
            description=(
                "Why acidity, tannin, sweetness and alcohol interact with fat, protein and "
                "heat."
            ),
            tags=("principles", "balance", "acid", "tannin"),
            keywords=(
                "principle", "principles", "pair", "pairing", "acid", "acidity", "tannin",
                "sweet", "sweetness", "fat", "protein", "salt", "spice", "heat", "balance",
            ),
            text=(
                "Match intensity first: a delicate dish is overwhelmed by a powerful wine. "
                "Acidity cuts fat, so crisp whites suit creamy and fried food. Tannin binds "
                "protein, which is why a tannic red works with steak but turns metallic with "
                "fish. Sweetness tames chilli heat, and salt in food softens tannin and "
                "acidity. High-alcohol wines amplify spicy heat, so keep them away from it."
            ),
        ),
        Skill(
            id="whites",
            name="White wines",
            description=(
                "Sauvignon Blanc, Chardonnay, Riesling and Chenin Blanc with the dishes they "
                "suit."
            ),
            tags=("white", "sauvignon", "chardonnay", "riesling"),
            keywords=(
                "white", "sauvignon", "blanc", "chardonnay", "riesling", "chenin", "pinot",
                "grigio", "grigio", "albariño", "albarino", "chablis", "sancerre",
            ),
            text=(
                "Sauvignon Blanc's herbal acidity suits goat cheese, asparagus and seafood; "
                "Sancerre and Pouilly-Fume are the benchmark. Chardonnay ranges from steely "
                "Chablis (oysters, shellfish) to oaked styles with butter and cream sauces. "
                "Riesling's sugar-acid balance is the classic answer to Thai, Indian and "
                "Sichuan heat. Chenin Blanc handles richer fish and pork with fruit and "
                "acidity."
            ),
        ),
        Skill(
            id="reds",
            name="Red wines",
            description=(
                "Cabernet Sauvignon, Pinot Noir, Syrah and Sangiovese matched to dishes."
            ),
            tags=("red", "cabernet", "pinot", "syrah"),
            keywords=(
                "red", "cabernet", "merlot", "pinot", "noir", "syrah", "shiraz", "sangiovese",
                "tempranillo", "malbec", "nebbiolo", "zinfandel", "steak", "lamb", "beef",
            ),
            text=(
                "Cabernet Sauvignon's tannin and cassis suit roast beef, lamb and hard cheese. "
                "Pinot Noir is light enough for duck, mushrooms and salmon, and it fails with "
                "heavy sauces. Syrah/Shiraz brings pepper and smoke to grilled meat and "
                "barbecue. Sangiovese's high acidity matches tomato-based pasta and pizza, "
                "while Nebbiolo's tannin needs braised beef or truffle dishes to soften it."
            ),
        ),
    ),
)
