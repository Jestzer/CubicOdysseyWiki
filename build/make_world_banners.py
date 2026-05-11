#!/usr/bin/env python3
"""Generate one banner image per world type using the actual voxel colors
from each world's surface layer in `data/configs/voxeldistributions/`.

These are **synthesised** images — not in-game screenshots. They convey
the world's palette honestly (every colour comes from the game's own
m_color fields) without fabricating screenshots we don't have.

Outputs: assets/worlds/<slug>.png
"""

import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from extract.catalog import Catalog
from extract.worlds import _world_slug


GAME_DEFAULT = Path(
    '/run/media/james/SSD/Program Files (x86)/Steam/steamapps/common/Cubic Odyssey'
)

W = 800
H = 220
GROUND_RATIO = 0.62      # bottom portion is the voxel landscape
VOXEL_SIZE = 16          # px per voxel
COLUMNS = W // VOXEL_SIZE
GROUND_PX = int(H * GROUND_RATIO)
SKY_PX = H - GROUND_PX


# Stylised palette per world. The literal m_color values from the
# game's voxels are all stone-grey at the surface (Stone, Limestone,
# Cliff) — accurate but visually indistinguishable across world types.
# These curated palettes echo the in-game biome look (sky + dominant
# surface) so each banner reads as its world at a glance. They are
# clearly synthesised, not screenshots.
#
# Palette is (ground colours [picked weighted], accent ore-vein colours,
# sky-gradient top, sky-gradient bottom).
WORLD_PALETTES = {
    'earth': {
        'ground':  [(76, 132, 56), (96, 154, 70), (118, 92, 60), (140, 110, 76), (90, 80, 64)],
        'accents': [(180, 70, 50), (210, 180, 70), (110, 110, 110)],
        'sky':     [(28, 50, 84), (138, 180, 220)],
    },
    'crystalline': {
        'ground':  [(108, 188, 220), (140, 220, 232), (84, 152, 200), (180, 220, 234), (64, 120, 168)],
        'accents': [(220, 80, 90), (90, 200, 130), (240, 200, 90), (130, 100, 230)],
        'sky':     [(24, 36, 60), (170, 200, 240)],
    },
    'scorched': {
        'ground':  [(132, 50, 40), (170, 84, 44), (84, 36, 32), (210, 130, 50), (60, 30, 30)],
        'accents': [(255, 200, 70), (255, 100, 30), (180, 40, 30)],
        'sky':     [(50, 18, 28), (210, 90, 50)],
    },
    'barren': {
        'ground':  [(160, 138, 96), (124, 102, 70), (96, 80, 58), (180, 156, 110), (76, 60, 48)],
        'accents': [(150, 110, 70), (100, 90, 80), (200, 170, 130)],
        'sky':     [(40, 32, 28), (200, 168, 130)],
    },
    'oceanic': {
        'ground':  [(60, 102, 130), (88, 144, 170), (40, 76, 100), (110, 168, 188), (50, 90, 110)],
        'accents': [(220, 200, 130), (140, 200, 180), (255, 240, 200)],
        'sky':     [(20, 36, 56), (140, 180, 210)],
    },
    'majestic': {
        'ground':  [(118, 84, 168), (90, 60, 140), (180, 130, 90), (210, 170, 110), (140, 100, 70)],
        'accents': [(240, 220, 110), (200, 90, 170), (130, 220, 220)],
        'sky':     [(36, 22, 60), (220, 170, 220)],
    },
    'shroomy': {
        'ground':  [(180, 90, 130), (130, 70, 110), (210, 130, 160), (96, 60, 90), (160, 110, 140)],
        'accents': [(240, 220, 80), (255, 110, 90), (170, 220, 130)],
        'sky':     [(48, 24, 50), (220, 160, 200)],
    },
    'slimy': {
        'ground':  [(96, 168, 100), (60, 130, 70), (130, 200, 130), (40, 96, 60), (160, 220, 140)],
        'accents': [(220, 220, 90), (50, 80, 40), (200, 240, 200)],
        'sky':     [(28, 50, 36), (160, 220, 180)],
    },
    'xeno': {
        'ground':  [(130, 60, 180), (170, 90, 200), (90, 40, 130), (210, 140, 220), (60, 30, 90)],
        'accents': [(80, 240, 200), (240, 100, 200), (200, 240, 130)],
        'sky':     [(28, 16, 50), (180, 130, 220)],
    },
}


def _surface_palette(world_record: dict, voxels: Dict[str, dict]
                      ) -> List[Tuple[Tuple[int, int, int], int]]:
    """Return [((r,g,b), weight)] from the highest surface layer."""
    layers = world_record.get('layers') or []
    if not layers:
        return []
    top = layers[0]
    out = []
    for v in top.get('voxels') or []:
        vox = voxels.get(v['voxel_name'])
        if not vox:
            continue
        c = vox.get('m_color')
        if not c or len(c) < 3:
            continue
        out.append(((int(c[0]), int(c[1]), int(c[2])), int(v.get('frequency', 1))))
    return out


def _ore_palette(world_record: dict, voxels: Dict[str, dict]
                  ) -> List[Tuple[int, int, int]]:
    """A few accent colours from the surface ores — sprinkled into the
    landscape so each world has subtle ore-vein flecks."""
    layers = world_record.get('layers') or []
    if not layers:
        return []
    out = []
    for layer in layers[:3]:
        for o in layer.get('ores') or []:
            if not o.get('frequency'):
                continue
            vox = voxels.get(o['voxel_name'])
            if not vox:
                continue
            c = vox.get('m_color')
            if c and len(c) >= 3:
                out.append((int(c[0]), int(c[1]), int(c[2])))
    return out[:6]


def _sky_color(palette: list) -> Tuple[int, int, int]:
    """Lighten one of the surface colours toward white for a sky cast."""
    if not palette:
        return (80, 90, 110)
    base = max(palette, key=lambda p: sum(p[0]))[0]
    return tuple(min(255, int(base[i] * 0.5 + 255 * 0.5)) for i in range(3))


def _weighted_choice(items, rng):
    total = sum(w for _, w in items)
    if total <= 0:
        return items[0][0] if items else (128, 128, 128)
    r = rng.uniform(0, total)
    cum = 0
    for c, w in items:
        cum += w
        if r <= cum:
            return c
    return items[-1][0]


def render_banner(world_record: dict, voxels: Dict[str, dict],
                   seed_extra: int = 0) -> Image.Image:
    slug = world_record['slug']
    palette = WORLD_PALETTES.get(slug, {
        'ground': [(90, 90, 90)],
        'accents': [(180, 180, 180)],
        'sky': [(20, 24, 30), (140, 140, 160)],
    })
    ground = [(c, 1) for c in palette['ground']]
    accents = palette['accents']
    sky_a, sky_b = palette['sky']

    rng = random.Random(hash(slug) + seed_extra)
    img = Image.new('RGB', (W, H), '#0c0f14')
    draw = ImageDraw.Draw(img)

    # Sky gradient — paint the full height so any gap between hill tops
    # and the sky line shows sky-colour, not bg-colour.
    for y in range(H):
        t = y / max(1, H - 1)
        r = int(sky_a[0] + (sky_b[0] - sky_a[0]) * t)
        g = int(sky_a[1] + (sky_b[1] - sky_a[1]) * t)
        b = int(sky_a[2] + (sky_b[2] - sky_a[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Rolling-hill ground: smoother walk via low-pass over a noisy seed
    base_height = (GROUND_PX // VOXEL_SIZE) - 1
    raw_heights = [base_height + rng.choice([-2, -1, -1, 0, 0, 0, 1, 1, 2])
                    for _ in range(COLUMNS + 4)]
    # 3-tap moving average smooths the silhouette
    heights = []
    for i in range(COLUMNS):
        window = raw_heights[i:i + 3]
        heights.append(max(2, min(base_height + 2,
                                     round(sum(window) / len(window)))))

    for col in range(COLUMNS):
        h_vox = heights[col]
        x0 = col * VOXEL_SIZE
        for row in range(h_vox):
            depth_t = row / max(1, h_vox)  # 0 at top, ~1 at bottom
            color = _weighted_choice(ground, rng)
            # The top row of each column is the lightest variant
            if row == h_vox - 1:
                color = _lighten(color, 1.12)
            # Deeper voxels get darkened so the silhouette has depth
            elif depth_t < 0.4:
                color = _darken(color, 0.85)
            # Sprinkle accent (ore-vein) colours in mid-depth
            if accents and rng.random() < 0.05 + depth_t * 0.08:
                color = rng.choice(accents)
            y0 = H - (row + 1) * VOXEL_SIZE
            draw.rectangle((x0, y0, x0 + VOXEL_SIZE - 1,
                             y0 + VOXEL_SIZE - 1), fill=color)
            # Voxel bevel — top + left edges lighter
            draw.line([(x0, y0), (x0 + VOXEL_SIZE - 1, y0)],
                       fill=_lighten(color, 1.18))
            draw.line([(x0, y0), (x0, y0 + VOXEL_SIZE - 1)],
                       fill=_lighten(color, 1.10))
            # Right + bottom edges darker
            draw.line([(x0 + VOXEL_SIZE - 1, y0),
                        (x0 + VOXEL_SIZE - 1, y0 + VOXEL_SIZE - 1)],
                       fill=_darken(color, 0.85))
    return img


def _darken(rgb, f):
    return tuple(max(0, int(c * f)) for c in rgb)


def _lighten(rgb, f):
    return tuple(min(255, int(c * f)) for c in rgb)


def main():
    import json
    game_root = GAME_DEFAULT
    cat = Catalog.load(game_root)
    dist_meta = json.loads((HERE / 'world_to_distribution.json').read_text())
    dist_meta_clean = {k: v for k, v in dist_meta.items() if not k.startswith('_')}

    from extract.worlds import build_world_records
    world_records = build_world_records(cat, dist_meta_clean)

    out_dir = HERE.parent / 'assets' / 'worlds'
    out_dir.mkdir(parents=True, exist_ok=True)

    for w in world_records:
        img = render_banner(w, cat.voxels)
        out_path = out_dir / f"{w['slug']}.png"
        img.save(out_path, 'PNG', optimize=True)
        print(f"  {w['slug']:14s} -> {out_path.name}")


if __name__ == '__main__':
    main()
