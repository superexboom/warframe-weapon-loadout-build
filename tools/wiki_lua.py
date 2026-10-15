"""Read the wiki's Lua data modules (``Module:*/data*``) into Python values.

    python tools/wiki_lua.py fetch DIR [primary secondary ...]

``fetch`` downloads ``Module:Weapons/data/<part>`` through the MediaWiki API
(``?action=raw`` is refused to scripts; ``api.php`` is not) and keeps the
revision timestamp next to the text. ``parse`` reads the table literals these
modules are made of: strings, numbers, booleans, nil and nested tables with
``Name =``, ``["Name"] =`` keys or positional items. Code (functions, calls)
is not supported; these modules hold none.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://wiki.warframe.com/api.php"
WEAPON_PARTS = ("primary", "secondary", "melee", "archwing", "companion", "modular", "misc")


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0

    def error(self, message: str) -> ValueError:
        line = self.text.count("\n", 0, self.i) + 1
        return ValueError(f"{message} at line {line}")

    def skip(self) -> None:
        text, n = self.text, len(self.text)
        while self.i < n:
            c = text[self.i]
            if c in " \t\r\n,;":
                self.i += 1
            elif text.startswith("--[[", self.i):
                end = text.find("]]", self.i)
                self.i = n if end < 0 else end + 2
            elif text.startswith("--", self.i):
                end = text.find("\n", self.i)
                self.i = n if end < 0 else end + 1
            else:
                break

    def value(self):
        self.skip()
        text = self.text
        c = text[self.i]
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        if text.startswith("[[", self.i) or text.startswith("[=[", self.i):
            close = "]]" if text.startswith("[[", self.i) else "]=]"
            start = self.i + (2 if close == "]]" else 3)
            end = text.index(close, start)
            self.i = end + len(close)
            return text[start:end]
        for word, result in (("true", True), ("false", False), ("nil", None), ("math.huge", float("inf"))):
            if text.startswith(word, self.i) and not (text[self.i + len(word):self.i + len(word) + 1].isalnum()):
                self.i += len(word)
                return result
        start = self.i
        while self.i < len(text) and (text[self.i].isalnum() or text[self.i] in ".-+xXeE"):
            self.i += 1
        token = text[start:self.i]
        if not token:
            raise self.error(f"unexpected {c!r}")
        return int(token, 16) if token.lower().startswith(("0x", "-0x")) else (
            float(token) if any(ch in token for ch in ".eE") and not token.lower().startswith("0x") else int(token))

    def string(self) -> str:
        quote = self.text[self.i]
        self.i += 1
        out = []
        while True:
            c = self.text[self.i]
            if c == "\\":
                nxt = self.text[self.i + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
            elif c == quote:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1

    def table(self):
        self.i += 1  # {
        keyed: dict = {}
        items: list = []
        while True:
            self.skip()
            if self.text[self.i] == "}":
                self.i += 1
                break
            key = None
            if self.text[self.i] == "[" and not self.text.startswith("[[", self.i):
                self.i += 1
                key = self.value()
                self.skip()
                if self.text[self.i] != "]":
                    raise self.error("expected ]")
                self.i += 1
                self.skip()
                if self.text[self.i] != "=":
                    raise self.error("expected =")
                self.i += 1
            else:
                start = self.i
                while self.i < len(self.text) and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
                    self.i += 1
                name = self.text[start:self.i]
                self.skip()
                if name and self.i < len(self.text) and self.text[self.i] == "=" and self.text[self.i + 1] != "=":
                    key = name
                    self.i += 1
                else:
                    self.i = start
            value = self.value()
            if key is None:
                items.append(value)
            else:
                keyed[key] = value
        if keyed and items:
            keyed.update({i + 1: v for i, v in enumerate(items)})
            return keyed
        return keyed if keyed else items


def parse(text: str):
    reader = _Reader(text)
    reader.skip()
    if reader.text.startswith("return", reader.i):
        reader.i += len("return")
    return reader.value()


def fetch(title: str) -> tuple[str, str]:
    query = urllib.parse.urlencode(dict(action="query", prop="revisions", rvprop="content|timestamp",
                                        rvslots="main", format="json", titles=title))
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "WF-Riven-Portable data audit"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    page = next(iter(data["query"]["pages"].values()))
    revision = page["revisions"][0]
    return revision["slots"]["main"]["*"], revision["timestamp"]


def load_weapons(directory: Path) -> dict[str, dict]:
    """Every weapon of the downloaded modules, keyed by internal path."""
    rows: dict[str, dict] = {}
    for part in WEAPON_PARTS:
        path = directory / f"{part}.lua"
        if not path.is_file():
            continue
        for name, row in parse(path.read_text(encoding="utf-8")).items():
            if isinstance(row, dict) and row.get("InternalName"):
                rows.setdefault(row["InternalName"], dict(row, _module=part, _key=name))
    return rows


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "fetch":
        print(__doc__)
        return 2
    directory = Path(argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    stamps = {}
    for part in argv[2:] or WEAPON_PARTS:
        text, stamp = fetch(f"Module:Weapons/data/{part}")
        (directory / f"{part}.lua").write_text(text, encoding="utf-8")
        stamps[part] = stamp
        print(part, stamp, len(text))
    (directory / "revisions.json").write_text(json.dumps(stamps, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
