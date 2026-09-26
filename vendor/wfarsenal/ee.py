"""Parse the text notation emitted by the game package exporter.

Braces hold either a struct (key=value) or an array; nested blocks and quoted
commas must retain their type. Empty blocks are represented by an empty list.
"""

from __future__ import annotations
import re
from typing import Any

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[{}=,]|\r?\n|[^{}=,\s]+')
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def parse_ee(text: str) -> dict[str, Any]:
    tokens = _TOKEN.findall(text.lstrip("\ufeff"))
    pos = 0

    def skip() -> None:
        nonlocal pos
        while pos < len(tokens) and tokens[pos] in ("\n", "\r\n", ","):
            pos += 1

    def scalar(token: str) -> Any:
        if token.startswith('"'):
            # Game paths use literal backslashes; do not apply Python escapes.
            return token[1:-1].replace('\\"', '"')
        if _NUMBER.fullmatch(token):
            return float(token) if any(c in token.lower() for c in ".e") else int(token)
        return token

    def value() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("missing package value")
        if tokens[pos] != "{":
            result = scalar(tokens[pos])
            pos += 1
            return result
        pos += 1
        skip()
        if pos < len(tokens) and tokens[pos] == "}":
            pos += 1
            return []
        is_struct = pos + 1 < len(tokens) and tokens[pos + 1] == "="
        result: Any = {} if is_struct else []
        while pos < len(tokens) and tokens[pos] != "}":
            if is_struct:
                key = tokens[pos]
                pos += 1
                if pos >= len(tokens) or tokens[pos] != "=":
                    raise ValueError(f"expected = after {key}")
                pos += 1
                if key in result:
                    raise ValueError(f"duplicate package key {key}")
                result[key] = value()
            else:
                result.append(value())
            skip()
        if pos >= len(tokens):
            raise ValueError("unterminated package block")
        pos += 1
        return result

    result = {}
    skip()
    while pos < len(tokens):
        key = tokens[pos]
        pos += 1
        if pos >= len(tokens) or tokens[pos] != "=":
            raise ValueError(f"expected = after {key}")
        pos += 1
        if key in result:
            raise ValueError(f"duplicate package key {key}")
        result[key] = value()
        skip()
    return result
