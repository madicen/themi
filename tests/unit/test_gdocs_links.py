"""RC1a: a doc id from what someone pasted."""

from __future__ import annotations

from tests.fixtures.cookbook import COOKBOOK_ID, LINK
from themi_google.connectors.gdocs import doc_id_from


def test_doc_ids_from_links_and_ids() -> None:
    assert doc_id_from(LINK) == COOKBOOK_ID
    assert doc_id_from(f"  {COOKBOOK_ID} ") == COOKBOOK_ID
    assert doc_id_from(f"https://docs.google.com/document/u/1/d/{COOKBOOK_ID}/view") is None
    assert doc_id_from(f"https://docs.google.com/document/d/{COOKBOOK_ID}") == COOKBOOK_ID
    assert doc_id_from("https://example.com/recipes") is None
    assert doc_id_from("short") is None
