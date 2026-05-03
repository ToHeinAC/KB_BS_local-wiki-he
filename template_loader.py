"""Loads the user-fillable insertion-metadata template."""

from pathlib import Path

import frontmatter

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "insert.md"


def load_insert_template() -> list[str]:
    """Return ordered list of metadata field names from templates/insert.md."""
    if not _TEMPLATE_PATH.exists():
        return []
    post = frontmatter.load(str(_TEMPLATE_PATH))
    return list(post.metadata.keys())
