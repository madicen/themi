"""SP3a: a small Markdown renderer for the modules' setup guides.

Guides are Themi's own text, but they're rendered without any raw HTML anyway: every
character is escaped first, and only these become markup: `#`, `##` and `###` headings,
paragraphs, `-` and `1.` lists, `**bold**`, `` `code` ``, and `[words](https://...)` links,
which open in a new tab. A link to anything but http(s) or a site path stays as text.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")
ORDERED = re.compile(r"^\d+\.\s+")


def _inline(text: str) -> str:
    out = str(escape(text))
    codes: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = CODE.sub(keep_code, out)  # code first, so nothing inside it becomes markup

    def link(match: re.Match[str]) -> str:
        words, url = match.group(1), match.group(2)
        if url.startswith(("https://", "http://")):
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{words}</a>'
        if url.startswith("/") and not url.startswith("//"):
            return f'<a href="{url}">{words}</a>'
        return match.group(0)

    out = LINK.sub(link, out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def render(text: str) -> Markup:
    html: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = ""

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            html.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            body = "".join(f"<li>{_inline(item)}</li>" for item in items)
            html.append(f"<{list_tag}>{body}</{list_tag}>")
            items.clear()
            list_tag = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        bullet = line.startswith(("- ", "* "))
        ordered = ORDERED.match(line)
        if heading:
            flush()
            level = len(heading.group(1)) + 1  # the page has its own h1
            html.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif bullet or ordered:
            tag = "ol" if ordered else "ul"
            if paragraph or (list_tag and list_tag != tag):
                flush()
            list_tag = tag
            items.append(line[ordered.end() :] if ordered else line[2:])
        elif items and raw.startswith((" ", "\t")):
            items[-1] += " " + line  # a list item carried on to the next line
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    return Markup("\n".join(html))
