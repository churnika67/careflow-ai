import hashlib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from ingestion.models import Section

CLEANER_VERSION = "cms-html-v1"
BLOCKS = {"p", "div", "li", "tr", "ul", "ol", "table", "h1", "h2", "h3", "h4"}


def clean_sections(raw: str, field: str) -> tuple[Section, ...]:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    links = []
    for link in soup.find_all("a", href=True):
        url = urljoin("https://www.cms.gov/medicare-coverage-database/view/", link["href"])
        if urlparse(url).scheme in {"http", "https"}:
            links.append(url)

    def render(node) -> str:
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        if node.name == "br":
            return "\n"
        if node.name == "img":
            return node.get("alt", "")
        body = "".join(render(child) for child in node.children)
        if node.name in {"td", "th"}:
            return body + " | "
        if node.name == "li":
            parent = node.parent
            if parent.name == "ol":
                index = list(parent.find_all("li", recursive=False)).index(node)
                start = int(parent.get("start", 1))
                kind = parent.get("type", "1")
                marker = chr(ord("a") + index) if kind == "a" else str(start + index)
                body = f"{marker}. {body}"
            else:
                body = "- " + body
        return f"\n{body}\n" if node.name in BLOCKS else body

    lines = [re.sub(r"\s+", " ", line).strip() for line in render(soup).splitlines()]
    lines = [line for line in lines if line]
    groups: list[tuple[str, list[str]]] = []
    heading, body = "", []
    for line in lines:
        # Actual NCD top-level headings use letters; numbered criteria stay with their section.
        if re.match(r"^[A-Z]\.\s+", line) and len(line) <= 160:
            if body:
                groups.append((heading, body))
            heading, body = line, [line]
        else:
            body.append(line)
    if body:
        groups.append((heading, body))
    return tuple(
        Section(
            field=field,
            ordinal=i,
            heading=title,
            text="\n\n".join(paragraphs),
            raw_field_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            links=tuple(dict.fromkeys(links)),
        )
        for i, (title, paragraphs) in enumerate(groups)
        if " ".join(paragraphs).strip()
    )
