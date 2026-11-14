"""Checks every page must pass before it is written: tags balance and there are no em dashes."""
from html.parser import HTMLParser


class _Balance(HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"unexpected </{tag}>")


def check_html(page):
    """Raise ValueError when the page's tags do not balance or it contains an em dash."""
    b = _Balance()
    b.feed(page)
    if b.errors or b.stack:
        raise ValueError(f"Page tags do not balance: {b.errors[:3]} open={b.stack[-3:]}")
    if "\u2014" in page:
        raise ValueError("Page contains an em dash")
