"""The family cookbook, read from its Google Doc (RC1a): pure functions, no I/O.

The doc ("Madicen Family Cookbook") is laid out with heading styles:

- Heading 1 is a section (Ingredients, Breakfast, Entrees, ..., References); Heading 2 or 3
  a sub-section (only Ingredients has them: Sauces, Meats...).
- Heading 4 starts a recipe. Heading 5 "Ingredients" and "Instructions" split it; Heading 6
  groups ingredients ("Masala Paste"). After the steps come notes ("Recipe Notes: ...") and
  "Source: ...", then a `-----` line.

The parser works over the Docs API's structure (paragraph styles, tables, each heading's
`headingId`), never over exported text. It is lenient where the doc is irregular, and says
so: a recipe it had to guess about is kept with a `needs_look` reason, never dropped.

- "Ingredients" or "Instructions" typed as a plain paragraph switches part as a heading would
  (Bean Dip, Ube Gelato).
- A second "Ingredients" after ingredient lines means the steps (Biryani).
- A recipe that is only a table is a chart (Roasted Vegetables): its rows are kept.
- Hand numbering ("1\\. ", "2) ") is taken off steps; the words are kept as written.

`entry_requests` (RC5) builds the batchUpdate that adds a recipe in the doc's own style.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Kind = Literal["recipe", "chart"]
Part = Literal["ingredients", "instructions", "after"]

SECTION_STYLES = ("HEADING_1", "TITLE")
SUBSECTION_STYLES = ("HEADING_2", "HEADING_3")
RECIPE_STYLE = "HEADING_4"
PART_STYLE = "HEADING_5"
GROUP_STYLE = "HEADING_6"
PART_WORDS: dict[str, Part] = {
    "ingredients": "ingredients",
    "ingredient": "ingredients",
    "instructions": "instructions",
    "directions": "instructions",
    "method": "instructions",
    "steps": "instructions",
}
SEPARATOR = re.compile(r"^\s*[-_\u2014\u2013]{3,}\s*$")  # dashes, em or en dashes
NUMBERING = re.compile(r"^\s*\d{1,2}\s*\\?[.)]\s+")
NOTE = re.compile(r"^\s*(?:recipe\s+)?(?:notes?|tips?|variations?)\s*[:\-]", re.IGNORECASE)
SOURCE = re.compile(r"^\s*source\s*:\s*", re.IGNORECASE)
YIELD = re.compile(
    r"\b(?:makes|serves|yields?)\s+(?:about\s+)?(\d{1,3})\b|\b(\d{1,3})\s+servings?\b",
    re.IGNORECASE,
)
REFERENCES = "references"


@dataclass(frozen=True)
class Line:
    text: str
    group: str = ""


@dataclass
class ParsedRecipe:
    key: str  # the doc's heading id: stable while the heading stays
    name: str
    section: str = ""
    subsection: str = ""
    ingredients: list[Line] = field(default_factory=list)
    steps: list[Line] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = ""
    kind: Kind = "recipe"
    chart: list[list[str]] = field(default_factory=list)
    yield_count: int | None = None
    needs_look: list[str] = field(default_factory=list)
    position: int = 0

    def content_hash(self) -> str:
        data = asdict(self)
        data.pop("position")
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def is_reference(self) -> bool:
        return self.section.strip().lower() == REFERENCES


@dataclass(frozen=True)
class Block:
    """One paragraph or table of the doc, flattened."""

    kind: Literal["paragraph", "table", "rule"]
    text: str = ""
    style: str = "NORMAL_TEXT"
    heading_id: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    start: int = 0  # the doc's index where it starts (RC5 writes before a heading)


@dataclass
class Cookbook:
    title: str
    revision: str
    recipes: list[ParsedRecipe]
    sections: list[tuple[str, int]]  # (Heading 1 text, the index its paragraph starts at)
    end: int  # the body's last index


# ----- the Docs API's structure -----------------------------------------------------------


def _paragraph_text(paragraph: dict[str, Any]) -> tuple[str, bool]:
    """Its text (soft line breaks kept as newlines), and whether it holds a horizontal rule."""
    parts: list[str] = []
    rule = False
    for element in paragraph.get("elements", []):
        if "textRun" in element:
            parts.append(str(element["textRun"].get("content", "")))
        elif "horizontalRule" in element:
            rule = True
    text = "".join(parts).replace("\u000b", "\n").rstrip("\n")
    return text, rule


def _cell_text(cell: dict[str, Any]) -> str:
    texts = [
        _paragraph_text(c["paragraph"])[0] for c in cell.get("content", []) if "paragraph" in c
    ]
    return " ".join(t.strip() for t in texts if t.strip())


def blocks(document: dict[str, Any]) -> list[Block]:
    out: list[Block] = []
    for element in document.get("body", {}).get("content", []):
        start = int(element.get("startIndex", 0))
        if "paragraph" in element:
            paragraph = element["paragraph"]
            text, rule = _paragraph_text(paragraph)
            style = paragraph.get("paragraphStyle", {})
            if rule and not text.strip():
                out.append(Block("rule", start=start))
                continue
            out.append(
                Block(
                    "paragraph",
                    text,
                    str(style.get("namedStyleType", "NORMAL_TEXT")),
                    str(style.get("headingId", "")),
                    start=start,
                )
            )
        elif "table" in element:
            rows = tuple(
                tuple(_cell_text(cell) for cell in row.get("tableCells", []))
                for row in element["table"].get("tableRows", [])
            )
            out.append(Block("table", rows=rows, start=start))
    return out


# ----- parsing ------------------------------------------------------------------------------


def _clean(text: str) -> str:
    return " ".join(text.replace("\\", "").split())


def _plain(text: str) -> str:
    """A heading's words without markdown-ish decoration: '*Masala Paste*' -> 'Masala Paste'."""
    return _clean(text).strip("*_: ").strip()


def _part_word(text: str) -> Part | None:
    return PART_WORDS.get(_plain(text).lower())


def _chart_rows(rows: tuple[tuple[str, ...], ...]) -> list[list[str]]:
    kept = [[_clean(c).strip("*") for c in row] for row in rows]
    return [row for row in kept if any(row)]


def parse(document: dict[str, Any]) -> Cookbook:
    title = _clean(str(document.get("title", "")))
    found: list[ParsedRecipe] = []
    sections: list[tuple[str, int]] = []
    section = subsection = ""
    recipe: ParsedRecipe | None = None
    part: Part | None = None
    group = ""
    step_group = ""
    end = 1
    for element in document.get("body", {}).get("content", []):
        end = max(end, int(element.get("endIndex", 0)))

    def finish() -> None:
        nonlocal recipe, part, group, step_group
        if recipe is not None:
            _settle(recipe)
            recipe.position = len(found)
            found.append(recipe)
        recipe, part, group, step_group = None, None, "", ""

    for block in blocks(document):
        if block.kind == "rule":
            finish()
            continue
        if block.kind == "table":
            rows = _chart_rows(block.rows)
            if recipe is None or not rows:
                continue
            if not recipe.ingredients and not recipe.steps:
                recipe.kind = "chart"
                recipe.chart.extend(rows)
            else:  # a table inside a recipe: kept with its notes, as lines
                recipe.notes.extend(" | ".join(r) for r in rows)
            continue
        text = block.text
        plain = _plain(text)
        style = block.style
        if style in SECTION_STYLES:
            finish()
            if plain and plain.lower() != title.lower():
                section, subsection = plain, ""
                sections.append((plain, block.start))
            continue
        if style in SUBSECTION_STYLES:
            finish()
            subsection = plain
            continue
        if style == RECIPE_STYLE:
            finish()
            if plain:
                key = block.heading_id or _fallback_key(section, plain, len(found))
                recipe = ParsedRecipe(key, plain, section, subsection)
            continue
        if recipe is None or not plain:
            continue
        if SEPARATOR.match(text):
            finish()
            continue
        word = _part_word(text) if style in (PART_STYLE, "NORMAL_TEXT", GROUP_STYLE) else None
        if word is not None and len(plain.split()) == 1:
            if style != PART_STYLE:
                _look(recipe, "headings typed as text")
            if word == "ingredients" and part == "ingredients" and recipe.ingredients:
                _look(recipe, "two Ingredients headings")
                word = "instructions"
            part = word
            continue
        if style == GROUP_STYLE:
            if part == "instructions":
                step_group = plain
            else:
                group = plain
                part = part or "ingredients"
            continue
        part = _add(recipe, part, text, group, step_group)
    finish()
    return Cookbook(title, str(document.get("revisionId", "")), found, sections, end)


def _add(recipe: ParsedRecipe, part: Part | None, text: str, group: str, step_group: str) -> Part:
    """Put a paragraph's lines where they belong; returns the part that follows."""
    now: Part = part or "ingredients"
    for raw in text.split("\n"):
        line = _clean(raw)
        if not line:
            continue
        if SOURCE.match(line):
            recipe.source = SOURCE.sub("", line)
            now = "after" if now == "instructions" else now
            continue
        if now == "ingredients":
            if NOTE.match(line):
                recipe.notes.append(line)
                continue
            if part is None:
                _look(recipe, "no Ingredients heading")
            recipe.ingredients.append(Line(line, group))
            continue
        if now == "after" or NOTE.match(line):
            recipe.notes.append(line)
            now = "after"
            continue
        recipe.steps.append(Line(NUMBERING.sub("", line), step_group))
    return now


def _settle(recipe: ParsedRecipe) -> None:
    """What's missing after the last line, and the yield if it's written down."""
    if recipe.kind == "recipe":
        if not recipe.ingredients:
            _look(recipe, "no ingredients found")
        if not recipe.steps:
            _look(recipe, "no steps found")
    for text in (
        *recipe.notes,
        *(s.text for s in recipe.steps),
        *(i.text for i in recipe.ingredients),
    ):
        found = YIELD.search(text)
        if found:
            recipe.yield_count = int(found.group(1) or found.group(2))
            break


def _look(recipe: ParsedRecipe, reason: str) -> None:
    if reason not in recipe.needs_look:
        recipe.needs_look.append(reason)


def _fallback_key(section: str, name: str, n: int) -> str:
    return "x." + hashlib.sha256(f"{section}|{name}|{n}".encode()).hexdigest()[:12]


# ----- chart text -------------------------------------------------------------------------


def chart_text(recipe: ParsedRecipe) -> str:
    """A chart as aligned lines: "Broccoli: Temp 400, Time 20 min, Prep Cut to florets"."""
    if not recipe.chart:
        return ""
    header, *rows = recipe.chart
    if not rows:
        return " | ".join(header)
    lines = []
    for row in rows:
        name, *rest = row
        pairs = [f"{h} {v}" for h, v in zip(header[1:], rest, strict=False) if v and v != "-"]
        lines.append(f"{name}: " + ", ".join(pairs))
    return "\n".join(lines)


# ----- writing an entry (RC5) -------------------------------------------------------------


def entry_text(
    name: str, ingredients: list[Line], steps: list[Line], notes: list[str], source: str
) -> list[tuple[str, str]]:
    """The paragraphs of a new entry, each with its style, as the doc writes them."""
    paragraphs: list[tuple[str, str]] = [(name, RECIPE_STYLE), ("Ingredients", PART_STYLE)]
    group = ""
    for line in ingredients:
        if line.group and line.group != group:
            paragraphs.append((line.group, GROUP_STYLE))
            group = line.group
        paragraphs.append((line.text, "NORMAL_TEXT"))
    paragraphs.append(("Instructions", PART_STYLE))
    step_group = ""
    for step in steps:
        if step.group and step.group != step_group:
            paragraphs.append((step.group, GROUP_STYLE))
            step_group = step.group
        paragraphs.append((step.text, "NORMAL_TEXT"))
    paragraphs.extend((note, "NORMAL_TEXT") for note in notes)
    if source:
        paragraphs.append((f"Source: {source}", "NORMAL_TEXT"))
    paragraphs.append(("-----", "NORMAL_TEXT"))
    return paragraphs


def entry_requests(at: int, paragraphs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """One insertText at `at`, then each paragraph's style set over its own range. Text
    inserted before a heading would take that heading's style, so every paragraph's style is
    set, plain ones too."""
    text = "".join(f"{p}\n" for p, _ in paragraphs)
    requests: list[dict[str, Any]] = [{"insertText": {"location": {"index": at}, "text": text}}]
    index = at
    for words, style in paragraphs:
        length = len(words) + 1
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": index, "endIndex": index + length},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            }
        )
        index += length
    return requests


def insert_at(cookbook: Cookbook, section: str) -> int:
    """Where a new entry in `section` goes: just before the next section's heading, or at the
    end of the doc."""
    names = [name.lower() for name, _ in cookbook.sections]
    if section.lower() in names:
        n = names.index(section.lower())
        if n + 1 < len(cookbook.sections):
            return cookbook.sections[n + 1][1]
    return max(1, cookbook.end - 1)
