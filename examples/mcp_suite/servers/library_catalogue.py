"""Library catalogue MCP server: ISBN lookup and loan status."""

from __future__ import annotations

from mcp_suite.common import Tool, build_server, run

CATALOGUE: dict[str, dict[str, object]] = {
    "9780262033848": {
        "title": "Introduction to Algorithms",
        "author": "Cormen, Leiserson, Rivest, Stein",
        "shelf": "QA76.6 .C662",
        "copies": 4,
        "on_loan": 3,
    },
    "9780132350884": {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "shelf": "QA76.76 .M37",
        "copies": 2,
        "on_loan": 2,
    },
    "9780140449136": {
        "title": "The Odyssey",
        "author": "Homer, translated by E. V. Rieu",
        "shelf": "PA4025 .R53",
        "copies": 6,
        "on_loan": 1,
    },
}


def find_by_isbn(isbn: str) -> str:
    """Look up a book by ISBN and report its shelf location and copies."""
    key = isbn.strip().replace("-", "")
    row = CATALOGUE.get(key)
    if row is None:
        known = ", ".join(sorted(CATALOGUE))
        return f"No catalogue record for ISBN {key}. Indexed ISBNs: {known}."
    available = int(row["copies"]) - int(row["on_loan"])
    return (
        f"{row['title']} by {row['author']} is shelved at {row['shelf']}. "
        f"{available} of {row['copies']} copies are available; {row['on_loan']} on loan."
    )


def is_available(isbn: str) -> str:
    """Answer only whether a copy of an ISBN is currently on the shelf."""
    key = isbn.strip().replace("-", "")
    row = CATALOGUE.get(key)
    if row is None:
        known = ", ".join(sorted(CATALOGUE))
        return f"No catalogue record for ISBN {key}. Indexed ISBNs: {known}."
    available = int(row["copies"]) - int(row["on_loan"])
    if available <= 0:
        return f"All {row['copies']} copies of {row['title']} are on loan."
    return f"{available} copy/copies of {row['title']} are on the shelf."


SERVER = build_server(
    "library-catalogue",
    (
        Tool(
            "Look up a book in the library catalogue by ISBN, for example 9780262033848. "
            "Returns title, author, shelf location and copies available.",
            find_by_isbn,
        ),
        Tool(
            "Check only whether any copy of an ISBN is currently available to borrow.",
            is_available,
        ),
    ),
)

if __name__ == "__main__":
    run("library-catalogue", SERVER)
