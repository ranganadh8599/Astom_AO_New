"""Legal citation agent: cases, statutes and secondary sources."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "legal-citation",
    skills=(
        Skill(
            id="cases",
            name="Case citations",
            description=(
                "Party names, reporter volume and first page, court and year, and short forms."
            ),
            tags=("case", "reporter", "citation"),
            keywords=(
                "case", "cases", "reporter", "citation", "cite", "court", "year", "volume",
                "page", "italic", "italicise", "pinpoint", "id", "ibid", "supra",
            ),
            text=(
                "A full case citation gives the case name in italics, the reporter volume, the "
                "reporter abbreviation, the first page and the deciding court and year: "
                "Brown v. Board of Education, 347 U.S. 483 (1954). Add a pinpoint after the "
                "first page for a specific passage (347 U.S. at 495). Use a short form after "
                "the first full cite, and 'id.' only when the immediately preceding citation "
                "is the same source."
            ),
        ),
        Skill(
            id="statutes",
            name="Statutory citations",
            description=(
                "Code titles and sections, session laws, and how to cite a regulation."
            ),
            tags=("statute", "code", "regulation"),
            keywords=(
                "statute", "statutes", "code", "section", "sections", "title", "act",
                "regulation", "regulations", "cfr", "usc", "session", "law", "chapter",
                "subsection",
            ),
            text=(
                "Cite a federal statute by title, code abbreviation and section: 42 U.S.C. "
                "§ 1983 (2018). Give the subsection only when you rely on it: 29 U.S.C. "
                "§ 157(3). Cite regulations to the Code of Federal Regulations: 40 C.F.R. "
                "§ 122.26 (2023). For a session law, give its public law number and the "
                "statutes-at-large volume and page. The year in parentheses is the code "
                "edition you consulted."
            ),
        ),
        Skill(
            id="secondary",
            name="Books and journals",
            description=(
                "Author, title, edition, publisher, year; journal volume, page and pinpoints."
            ),
            tags=("book", "journal", "article"),
            keywords=(
                "book", "books", "journal", "article", "author", "editor", "edition",
                "publisher", "press", "volume", "issue", "pages", "secondary", "treatise",
                "law", "review",
            ),
            text=(
                "A book: Author, Title page (edition, Publisher Year). A journal article: "
                "Author, Title of Article, Volume Journal Page (Year), with a pinpoint after "
                "the first page. Use small capitals for author names in academic styles, and "
                "give the full first name or initials consistently. For a treatise, cite the "
                "section rather than the page when the work is organised that way, and check "
                "the pocket part or supplement for the current rule."
            ),
        ),
    ),
)
