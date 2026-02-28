"""MkDocs hook that computes reading time for each page."""

import math
import re

BADGE_HTML = (
    '<div class="reading-time">'
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/>'
    '<polyline points="12 6 12 12 16 14"/></svg>'
    '<span>~{minutes} min read</span></div>'
)


def on_page_markdown(markdown: str, page, config, files, **kwargs):
    """Estimate page reading time from markdown content and store it in page metadata."""
    # Strip YAML front matter
    text = re.sub(r"^---.*?---", "", markdown, count=1, flags=re.DOTALL)
    # Strip code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip markdown syntax (links, images, emphasis markers)
    text = re.sub(r"[#*_`\[\]()!|>~]", " ", text)
    words = len(text.split())
    page.meta["readtime"] = max(1, math.ceil(words / 230))
    return markdown


def on_post_page(output: str, page, config, **kwargs):
    """Inject the rendered reading-time badge into the first page heading."""
    minutes = page.meta.get("readtime")
    if not minutes:
        return output
    badge = BADGE_HTML.format(minutes=minutes)
    # Insert after the first closing </h1> tag
    return output.replace("</h1>", "</h1>" + badge, 1)
