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
# RC8c: an ingredient group of things to have, not to buy ("Tools"), and step groups that are
# notes, not steps ("Variations", "Make it a Meal")
TOOLS = "\x00tools"  # the group a Tools heading starts (never a heading's own words)
TOOL_GROUPS = {"tools", "tool", "equipment", "supplies", "you'll need", "you will need"}
NOTE_GROUPS = {"variations", "variation", "serving", "to serve", "make it a meal", "notes"}
# RC8c: sections of recipes that aren't ready to cook as written
DRAFTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bto convert\b", re.IGNORECASE), "not converted yet"),
    (re.compile(r"\bexperiments?\b", re.IGNORECASE), "an experiment"),
    (re.compile(r"^(?:ideas|someday)\b", re.IGNORECASE), "an idea"),
)


def draft_of(section: str) -> str:
    """RC8c: why a section's recipes aren't ready ("not converted yet"), or ""."""
    return next((said for pattern, said in DRAFTS if pattern.search(section)), "")


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
    tools: list[str] = field(default_factory=list)  # RC8c: what to have out, not to buy
    draft: str = ""  # RC8c: "not converted yet", from its section

    def content_hash(self) -> str:
        data = asdict(self)
        data.pop("position")
        for unset in ("tools", "draft"):  # RC8c: a recipe without them hashes as before
            if not data[unset]:
                data.pop(unset)
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


def _section_styles(found: list[Block], title: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """RC8c: which heading levels are sections and sub-sections. Heading 1 is a section,
    unless the only one is the doc's title: then Heading 2 is, and Heading 3 a sub-section."""
    tops = [
        _plain(b.text)
        for b in found
        if b.kind == "paragraph" and b.style in SECTION_STYLES and _plain(b.text)
    ]
    if title:
        tops = [t for t in tops if t.lower() != title.lower()]
    elif tops:
        tops = tops[1:]  # no file name: the first one is the title
    if tops or not any(b.style == "HEADING_2" for b in found if b.kind == "paragraph"):
        return SECTION_STYLES, SUBSECTION_STYLES
    return (*SECTION_STYLES, "HEADING_2"), ("HEADING_3",)


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

    every = blocks(document)
    section_styles, subsection_styles = _section_styles(every, title)
    for block in every:
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
        if style in section_styles:
            finish()
            if style in SECTION_STYLES and section_styles != SECTION_STYLES:
                continue  # RC8c: the title, above the sections
            if plain and plain.lower() != title.lower():
                section, subsection = plain, ""
                sections.append((plain, block.start))
            continue
        if style in subsection_styles:
            finish()
            subsection = plain
            continue
        if style == RECIPE_STYLE:
            finish()
            if SEPARATOR.match(_clean(text)):  # RC8c: a divider styled as a heading
                continue
            if plain:
                key = block.heading_id or _fallback_key(section, plain, len(found))
                recipe = ParsedRecipe(key, plain, section, subsection)
                recipe.draft = draft_of(section)
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
            named = plain.lower()
            if named in TOOL_GROUPS:  # RC8c: things to have out, never bought
                group, part = TOOLS, "ingredients"
            elif named in NOTE_GROUPS and part in ("instructions", "after"):
                recipe.notes.append(f"{plain}:")  # RC8c: variations are notes, not steps
                part = "after"
            elif part == "after" and recipe.steps:
                step_group, part = plain, "instructions"  # steps again after the notes
            elif part == "instructions":
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
            if group == TOOLS:  # RC8c
                recipe.tools.append(line)
                continue
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


# An ingredient line: an amount first ("1 Cup yogurt", "½ tsp vanilla", "2 Tbsp agave"),
# short, and no sentence after it.
INGREDIENT_LINE = re.compile(
    r"^(?:\d+(?:[./]\d+)?|[½¼¾⅓⅔⅛]|\d+\s?[½¼¾⅓⅔⅛])\s*"
    r"(?:cups?|tbsps?|tsps?|tablespoons?|teaspoons?|g|grams?|kg|oz|ounces?|lbs?|pounds?|ml|"
    r"l|liters?|litres?|pinch(?:es)?|cloves?|cans?|sticks?|pieces?|dash(?:es)?)?\.?\s"
    r"[^.!?]{1,60}$",
    re.IGNORECASE,
)


def _ingredient_groups(recipe: ParsedRecipe) -> None:
    """F50d (recipe 42's "Sweetening"): a group under the method, after its steps, whose
    lines are all ingredient lines is more ingredients, under that group's name."""
    for name in dict.fromkeys(s.group for s in recipe.steps if s.group):
        lines = [s for s in recipe.steps if s.group == name]
        first = recipe.steps.index(lines[0])
        if first == 0 or not all(INGREDIENT_LINE.match(s.text) for s in lines):
            continue
        recipe.steps = [s for s in recipe.steps if s.group != name]
        recipe.ingredients.extend(Line(s.text, name) for s in lines)


def _settle(recipe: ParsedRecipe) -> None:
    """What's missing after the last line, and the yield if it's written down."""
    if recipe.kind == "recipe":
        _ingredient_groups(recipe)
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


def entry_range(document: dict[str, Any], key: str, name: str = "") -> tuple[int, int] | None:
    """F49i: where an entry is in the doc, to delete it: from its Heading 4 through its
    `-----` (or a rule), or up to the next entry's or section's heading, or the doc's end.
    Found by its heading id, or by its name for a heading without one."""
    found = blocks(document)
    end = 1
    for element in document.get("body", {}).get("content", []):
        end = max(end, int(element.get("endIndex", 0)))
    headings = (*SECTION_STYLES, *SUBSECTION_STYLES, RECIPE_STYLE)
    first = next(
        (
            n
            for n, b in enumerate(found)
            if b.kind == "paragraph"
            and b.style == RECIPE_STYLE
            and (b.heading_id == key or (not b.heading_id and name and _plain(b.text) == name))
        ),
        None,
    )
    if first is None:
        return None
    for n in range(first + 1, len(found)):
        block = found[n]
        if block.kind == "rule" or (block.kind == "paragraph" and SEPARATOR.match(block.text)):
            after = found[n + 1].start if n + 1 < len(found) else end - 1
            return found[first].start, after
        if block.kind == "paragraph" and block.style in headings:
            return found[first].start, block.start
    return found[first].start, end - 1


def delete_requests(at: tuple[int, int]) -> list[dict[str, Any]]:
    return [{"deleteContentRange": {"range": {"startIndex": at[0], "endIndex": at[1]}}}]
