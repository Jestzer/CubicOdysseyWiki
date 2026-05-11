"""BSPR sprite-atlas parser, ported from CubicOdysseyVault.Core SpriteAtlas.cs.

A BSPR file lists rectangles into a paired PNG (e.g. items01.bspr →
items01.png). Each frame is a 12-byte record:

    [u32 reserved=0][u16 x][u16 y][u16 w][u16 h]

Records with reserved != 0 or zero/oversized dims are header/padding sentinels
and surface as None. Item .cfg files reference frames by index via inv_frame.

The records area ends where the trailing index table begins (small u16, small
u16 tuples) or at the embedded ASCII filename, whichever comes first.
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class SpriteFrame:
    x: int
    y: int
    w: int
    h: int


def _find_ascii(buf: bytes, needle: bytes) -> int:
    return buf.find(needle)


def _find_trailer_start(buf: bytes) -> int:
    name_off = _find_ascii(buf, b'items01.png')
    if name_off <= 0:
        name_off = _find_ascii(buf, b'items_dpl.png')
    if name_off <= 0:
        name_off = _find_ascii(buf, b'icons.png')
    data_end = name_off if name_off > 0 else len(buf)

    # Walk forward for a stretch of (small-u16, small-u16) pairs that look like
    # the trailing index table (frame_id < 5000, count <= 16).
    off = 8
    while off + 16 <= data_end:
        a = struct.unpack_from('<H', buf, off)[0]
        b = struct.unpack_from('<H', buf, off + 2)[0]
        if a >= 5000 or b > 16:
            off += 4
            continue
        consistent = True
        j = off
        while j + 4 <= data_end:
            aa = struct.unpack_from('<H', buf, j)[0]
            bb = struct.unpack_from('<H', buf, j + 2)[0]
            if aa >= 5000 or bb > 16:
                consistent = False
                break
            j += 4
        if consistent:
            return off
        off += 4

    return data_end


def parse_bspr(buf: bytes) -> List[Optional[SpriteFrame]]:
    if len(buf) < 12 or buf[:4] != b'BSPR':
        return []
    data_end = _find_trailer_start(buf)
    frames: List[Optional[SpriteFrame]] = []
    off = 8
    while off + 12 <= data_end:
        reserved, x, y, w, h = struct.unpack_from('<I H H H H', buf, off)
        if reserved == 0 and 0 < w <= 4096 and 0 < h <= 4096:
            frames.append(SpriteFrame(x, y, w, h))
        else:
            frames.append(None)
        off += 12
    return frames


def parse_bspr_file(path) -> List[Optional[SpriteFrame]]:
    return parse_bspr(Path(path).read_bytes())


if __name__ == '__main__':
    import sys
    frames = parse_bspr_file(sys.argv[1])
    print(f'Total frames: {len(frames)}')
    valid = [(i, f) for i, f in enumerate(frames) if f is not None]
    print(f'Non-null frames: {len(valid)}')
    for i, f in valid[:10]:
        print(f'  frame[{i}] = ({f.x},{f.y}) {f.w}x{f.h}')
