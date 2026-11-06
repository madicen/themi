# ruff: noqa: RUF001, RUF002, RUF003
# (recipes write fractions as ½ and ⅓, ranges with en dashes, and "×3")
"""Quantities as recipes write them, and scaling them (RC2b).

Parsing: "1½", "1 ½", "1 1/2", "½", "1.5", "3-4", "¼ –½" (ranges), "1 Tbsp + 1 tsp".
Writing: fractions for cups and spoons (and plain counts), whole numbers for grams and
millilitres, and for things that come whole (cans, packages, eggs) a rounded-up count with
the exact amount alongside: "2 cans (1½ needed)".

Only a line's leading amount is scaled, with any weight or volume in brackets right after it
("1 Cup cashews (130g)"): a size inside the line ("1 11oz package") and the numbers in a note
("soaked for 10 minutes") are left as written. A line with no leading amount is left alone.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

FRACTIONS = {
    "½": 1 / 2, "¼": 1 / 4, "¾": 3 / 4, "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8,
}  # fmt: skip
GLYPHS = "".join(FRACTIONS)
DASHES = "-–—"
NUMBER = rf"(?:\d+\s*[{GLYPHS}]|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[{GLYPHS}])"
SPOONS = r"cups?|c\.|tbsps?\.?|tablespoons?|tsps?\.?|teaspoons?"
METRIC = r"g|grams?|kg|ml|mls|millilit(?:er|re)s?|l|lit(?:er|re)s?"
WEIGHTS = r"oz\.?|ounces?|lbs?\.?|pounds?"
WHOLE = (
    r"cans?|tins?|packages?|packs?|jars?|bottles?|bags?|boxes|box|sticks?|heads?|bunch(?:es)?|"
    r"sheets?|batch(?:es)?|eggs?|cloves?|blocks?|loaf|loaves"
)
OTHER = r"pinch(?:es)?|dash(?:es)?|handfuls?|sprigs?|slices?|pieces?|inch(?:es)?|scoops?|drops?"
UNITS = f"{SPOONS}|{METRIC}|{WEIGHTS}|{WHOLE}|{OTHER}"
AMOUNT = re.compile(
    rf"(?P<low>{NUMBER})(?:\s*(?:[{DASHES}]|to)\s*(?P<high>{NUMBER}))?"
    rf"(?:\s*(?P<unit>(?:{UNITS}))(?![a-z]))?",
    re.IGNORECASE,
)
BRACKET = re.compile(
    rf"\s*\((?P<inside>\s*{NUMBER}(?:\s*(?:[{DASHES}]|to)\s*{NUMBER})?\s*(?:{UNITS})(?![a-z])"
    r"\.?\s*)\)",
    re.IGNORECASE,
)
TRAILING = re.compile(
    rf"\s*\((?P<inside>\s*{NUMBER}\s*(?:{METRIC}|{WEIGHTS})(?![a-z])\.?\s*)\)\s*$",
    re.IGNORECASE,
)
PLUS = re.compile(r"\s*\+\s*")
LEADING_WORDS = re.compile(r"^\s*(?:optional\s*:\s*|about\s+|approx\.?\s+|~\s*)", re.IGNORECASE)


def number(text: str) -> float:
    """'1½', '1 1/2', '1/2', '1.5', '½' -> a number."""
    text = text.strip()
    total = 0.0
    for glyph, value in FRACTIONS.items():
        if glyph in text:
            total += value
            text = text.replace(glyph, " ")
    for part in text.split():
        if "/" in part:
            top, bottom = part.split("/", 1)
            total += float(top) / float(bottom) if float(bottom) else 0.0
        else:
            total += float(part)
    return total


def _kind(unit: str) -> str:
    unit = unit.lower().rstrip(".")
    if not unit:
        return "count"
    for name, pattern in (("spoon", SPOONS), ("metric", METRIC), ("weight", WEIGHTS),
                          ("whole", WHOLE)):  # fmt: skip
        if re.fullmatch(f"(?:{pattern})", unit, re.IGNORECASE) or re.fullmatch(
            f"(?:{pattern})", unit + ".", re.IGNORECASE
        ):
            return name
    return "other"


def fraction(value: float) -> str:
    """1.5 -> '1½', 0.333 -> '⅓', 2.0 -> '2'; to the nearest eighth or third."""
    whole = math.floor(value + 1e-9)
    rest = value - whole
    _, glyph = min(
        ((abs(rest - v), g) for g, v in (*FRACTIONS.items(), ("", 0.0), ("+", 1.0))),
        key=lambda pair: pair[0],
    )
    if glyph == "+":
        whole, glyph = whole + 1, ""
    if whole == 0 and not glyph:
        return fraction_floor(value)
    return f"{whole}{glyph}" if whole else glyph


def fraction_floor(value: float) -> str:
    """A very small amount still shows as something: at least ⅛."""
    return "⅛" if value > 0 else "0"


def write(value: float, unit: str) -> str:
    """A scaled amount in the unit's own way of writing it."""
    kind = _kind(unit)
    if kind == "metric":
        rounded = round(value / 5) * 5 if value >= 100 else round(value)
        return str(max(int(rounded), 1))
    if kind == "weight":
        return fraction(value) if value < 10 else str(round(value))
    return fraction(value)


@dataclass(frozen=True)
class Scaled:
    line: str
    amount: str  # the scaled leading amount with its unit ("2 Cups (260g)"), or ""
    changed: bool


def _scaled_amount(match: re.Match[str], factor: float) -> str:
    unit = match.group("unit") or ""
    kind = _kind(unit)
    low = number(match.group("low")) * factor
    high = number(match.group("high")) * factor if match.group("high") else None
    if kind == "whole" and (low % 1 or (high is not None and high % 1)):
        exact = fraction(low) + (f"-{fraction(high)}" if high is not None else "")
        needed = math.ceil((high if high is not None else low) - 1e-9)
        return f"{needed} {_plural(unit, needed)} ({exact} needed)"
    text = write(low, unit) + (f"-{write(high, unit)}" if high is not None else "")
    if unit:
        top = high if high is not None else low
        attached = re.fullmatch(r"g|kg|ml|mls|l", unit, re.I)  # "260g", but "260 grams"
        text += unit if attached else f" {_plural(unit, top)}"
    return text


COUNTED = re.compile(
    r"(cup|can|tin|package|pack|jar|bottle|bag|stick|head|sheet|egg|clove|block|slice|piece|"
    r"sprig|handful|scoop|drop)s?",
    re.IGNORECASE,
)


def _plural(unit: str, value: float) -> str:
    """'Cup' for one or less, 'Cups' for more; other units are left as written."""
    if found := re.fullmatch(r"(batch|bunch|box)(?:es)?", unit, re.IGNORECASE):
        return found.group(1) if value <= 1 + 1e-9 else found.group(1) + "es"
    found = COUNTED.fullmatch(unit)
    if found is None:
        return unit
    base = found.group(1) if unit[: len(found.group(1))] == found.group(1) else unit.rstrip("sS")
    return base if value <= 1 + 1e-9 else base + "s"


def scale_line(line: str, factor: float) -> Scaled:
    """The line with its leading amount (and the weight or volume in brackets after it)
    scaled by `factor`."""
    if abs(factor - 1) < 1e-9:
        return Scaled(line, leading_amount(line), False)
    prefix = LEADING_WORDS.match(line)
    start = prefix.end() if prefix else 0
    out = line[:start]
    pos = start
    pieces: list[str] = []
    while True:
        match = AMOUNT.match(line, pos)
        if match is None:
            break
        scaled = _scaled_amount(match, factor)
        pieces.append(scaled)
        out += scaled
        pos = match.end()
        bracket = BRACKET.match(line, pos)
        if bracket is not None:
            inner = AMOUNT.match(bracket.group("inside").strip())
            if inner is not None:
                text = f" ({_scaled_amount(inner, factor)})"
                out += text
                pieces[-1] += text
                pos = bracket.end()
        plus = PLUS.match(line, pos)
        if plus is None or AMOUNT.match(line, plus.end()) is None:
            break
        out += " + "
        pos = plus.end()
    if not pieces:
        return Scaled(line, "", False)
    rest = line[pos:]
    trailing = TRAILING.search(rest)  # "..., soaked for 10 minutes (130g)": the weight too
    amount = " + ".join(pieces)
    if trailing is not None and (inner := AMOUNT.match(trailing.group("inside").strip())):
        weight = f" ({_scaled_amount(inner, factor)})"
        rest = rest[: trailing.start()] + weight + rest[trailing.end() :]
        amount += weight
    return Scaled(out + rest, amount, True)


def leading_amount(line: str) -> str:
    """The amount at the front of a line, as written ("1 Cup (130g)"), or ""."""
    prefix = LEADING_WORDS.match(line)
    start = prefix.end() if prefix else 0
    match = AMOUNT.match(line, start)
    if match is None:
        return ""
    end = match.end()
    bracket = BRACKET.match(line, end)
    if bracket is not None:
        end = bracket.end()
    amount = line[start:end].strip()
    trailing = TRAILING.search(line, end)
    return f"{amount} ({trailing.group('inside').strip()})" if trailing else amount


# ----- what they asked for --------------------------------------------------------------

WORDS = {
    "half": 0.5, "halve": 0.5, "halved": 0.5, "half batch": 0.5, "a half batch": 0.5,
    "double": 2.0, "doubled": 2.0, "twice": 2.0, "double batch": 2.0, "a double batch": 2.0,
    "triple": 3.0, "tripled": 3.0, "triple batch": 3.0, "quadruple": 4.0,
    "": 1.0, "1": 1.0, "normal": 1.0, "as written": 1.0, "single": 1.0,
}  # fmt: skip
TIMES = re.compile(r"^(?:[x×]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*[x×]|(\d+(?:\.\d+)?)\s*times)$")
FOR = re.compile(r"^(?:for|serves?|feeds?)?\s*(\d+)(?:\s*(?:people|servings?|portions?|of us))?$")


class NeedsYield(Exception):
    """'For 6' needs to know how many the recipe makes as written."""


def scale_for(text: str, makes: int | None) -> float:
    """'half', 'double', 'x3', 'for 6' -> the factor. ValueError if it isn't one."""
    said = " ".join(text.lower().replace("batch of", "batch").split()).strip(" .!")
    said = re.sub(r"\b(?:a|the)\s+(?=(?:half|double|triple))", "", said)
    if said in WORDS:
        return WORDS[said]
    if found := TIMES.match(said):
        return float(next(g for g in found.groups() if g))
    if found := FOR.match(said):
        if not makes:
            raise NeedsYield(said)
        return int(found.group(1)) / makes
    raise ValueError(f"{text!r} isn't an amount to scale by")


def describe(text: str, factor: float) -> str:
    """How the card names the batch: 'a double batch of', 'half of', 'for 6'."""
    said = text.strip().lower()
    if found := FOR.match(said):
        return f"for {found.group(1)}"
    names = {0.5: "half of", 2.0: "a double batch of", 3.0: "a triple batch of"}
    return names.get(factor, f"{fraction(factor)}× of")
