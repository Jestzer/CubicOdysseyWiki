"""Parser for Cubic Odyssey's plain-text config (.cfg) files.

The game ships per-item / per-voxel / per-recipe / per-distribution settings as
plaintext blocks like:

    VoxelCfg
    {
        name        "Iron"
        m_tier      1
        m_color     [99,95,94,255]
        m_layerCfgs
        {
            length 6
            LayerCfg { m_startY 100  m_endY 200  ... }
            LayerCfg { ... }
            ...
        }
    }

This module returns the top-level body as a nested dict. Blocks introduced by
`length N` (followed by N typed sub-blocks) collapse into a list of dicts.
"""

import re
from typing import Any, Optional, Union

_TOKEN_RE = re.compile(
    r'"([^"]*)"'           # quoted string (group 1)
    r'|(\{|\}|\[|\]|,)'    # punctuation (group 2)
    r'|([^\s\{\}\[\],]+)'  # bare word / number (group 3)
)


def _tokenize(text: str):
    text = re.sub(r'//[^\n]*', '', text)
    out = []
    for m in _TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            out.append(('STR', m.group(1)))
        elif m.group(2) is not None:
            out.append(('PUNCT', m.group(2)))
        else:
            out.append(('WORD', m.group(3)))
    return out


def _scalar(s: str) -> Any:
    sl = s.lower()
    if sl == 'true':
        return True
    if sl == 'false':
        return False
    if sl == 'null':
        return None
    try:
        if any(c in s for c in '.eE') and not s.lower().startswith('0x'):
            return float(s)
        return int(s, 0)
    except ValueError:
        return s


class _TokenStream:
    __slots__ = ('t', 'p')

    def __init__(self, tokens):
        self.t = tokens
        self.p = 0

    def peek(self):
        return self.t[self.p] if self.p < len(self.t) else None

    def take(self):
        v = self.peek()
        self.p += 1
        return v


def _parse_inline_array(ts: _TokenStream) -> list:
    out = []
    while True:
        tok = ts.peek()
        if tok is None:
            break
        if tok == ('PUNCT', ']'):
            ts.take()
            break
        if tok == ('PUNCT', ','):
            ts.take()
            continue
        kind, v = ts.take()
        out.append(v if kind == 'STR' else _scalar(v))
    return out


def _parse_body(ts: _TokenStream) -> Union[dict, list]:
    entries: dict = {}
    items: list = []
    saw_length = False

    while True:
        tok = ts.peek()
        if tok is None:
            break
        if tok == ('PUNCT', '}'):
            ts.take()
            break

        kind, word = ts.take()
        if word == 'length':
            ts.take()
            saw_length = True
            continue

        nxt = ts.peek()
        if nxt == ('PUNCT', '{'):
            ts.take()
            body = _parse_body(ts)
            if saw_length:
                items.append(body)
            else:
                entries[word] = body
        elif nxt == ('PUNCT', '['):
            ts.take()
            entries[word] = _parse_inline_array(ts)
        elif nxt is None:
            entries[word] = None
            break
        else:
            kind2, val = ts.take()
            entries[word] = val if kind2 == 'STR' else _scalar(val)

    return items if saw_length else entries


def parse(text: str) -> Optional[Union[dict, list]]:
    """Parse a .cfg text. Returns the top-level block body."""
    tokens = _tokenize(text)
    ts = _TokenStream(tokens)
    if ts.peek() is None:
        return None
    _, _name = ts.take()
    nxt = ts.peek()
    if nxt != ('PUNCT', '{'):
        return None
    ts.take()
    return _parse_body(ts)


def parse_file(path) -> Optional[Union[dict, list]]:
    with open(path, encoding='utf-8', errors='replace') as f:
        return parse(f.read())


if __name__ == '__main__':
    import sys
    import json
    body = parse_file(sys.argv[1])
    print(json.dumps(body, indent=2, default=str))
