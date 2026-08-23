"""Strict extraction of evidence embedded in a generated HTML report."""

from html.parser import HTMLParser


class ReportEvidenceParser(HTMLParser):
    """Extract the named JSON script without depending on attribute order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._collecting = False
        self._parts: list[str] = []
        self.payload: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if (
            tag == "script"
            and attributes.get("id") == "eii-data"
            and attributes.get("type") == "application/json"
        ):
            self._collecting = True

    def handle_data(self, data: str) -> None:
        if self._collecting:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._collecting:
            self.payload = "".join(self._parts)
            self._collecting = False
