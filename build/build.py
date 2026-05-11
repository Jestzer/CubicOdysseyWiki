#!/usr/bin/env python3
"""Build the local Cubic Odyssey HTML wiki.

Reads the game's data/configs and data/sprites, then writes:
  ../index.html, ../<category>.html, ../<category>/<slug>.html
  ../assets/icons/<slug>.png  (sliced from items01.png / items_dpl.png)
  ../assets/data.json         (search manifest)
  ../data/catalog.json        (full intermediate, for debugging)
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
WIKI = HERE.parent
sys.path.insert(0, str(HERE))

from parsers.bspr import parse_bspr_file, SpriteFrame
from extract.catalog import Catalog
from extract.ores import build_ore_records, _humanize, _slug
from extract.guides import (
    motherboard_context, mining_context, trading_context, all_guide_summaries,
)
from render.pages import WikiRenderer

DEFAULT_GAME_PATH = Path(
    '/run/media/james/SSD/Program Files (x86)/Steam/steamapps/common/Cubic Odyssey'
)


# ---------------------------------------------------------------------- icons

def _load_atlases(game_root: Path):
    """Return [(frames, image_path), ...] for atlases we'll try in order."""
    from PIL import Image
    sprites = game_root / 'data' / 'sprites'
    atlases = []
    for stem in ('items01', 'items_dpl'):
        bspr = sprites / f'{stem}.bspr'
        png = sprites / f'{stem}.png'
        if bspr.exists() and png.exists():
            frames = parse_bspr_file(bspr)
            img = Image.open(png).convert('RGBA')
            atlases.append((stem, frames, img))
    return atlases


def _lookup_frame(atlases, inv_frame: int, prefer_dpl: bool):
    # The .cfg's inv_frame is offset by +1 from the BSPR raw record index:
    # records 0 and 1 hold file header / metadata (reserved!=0 or 1x1 sentinel),
    # then game inv_frame=N maps to the BSPR record at index N+1.
    if inv_frame is None or inv_frame < 0:
        return None, None
    idx = inv_frame + 1
    order = list(atlases)
    if prefer_dpl and len(order) >= 2:
        order = [atlases[1], atlases[0]]
    for stem, frames, img in order:
        if 0 <= idx < len(frames) and frames[idx] is not None:
            return frames[idx], img
    return None, None


def slice_icons(items: Dict[str, dict], atlases, out_dir: Path) -> int:
    """Crop one PNG per item we want to show. Returns count written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for ident, item in items.items():
        inv = item.get('inv_frame')
        if inv is None:
            continue
        prefer_dpl = item.get('type') == 'DEPLOYABLE'
        frame, img = _lookup_frame(atlases, inv, prefer_dpl)
        if frame is None or img is None:
            continue
        crop = img.crop((frame.x, frame.y, frame.x + frame.w, frame.y + frame.h))
        out_path = out_dir / (_slug(ident) + '.png')
        crop.save(out_path, 'PNG', optimize=True)
        written += 1
    return written


# ---------------------------------------------------------------- categorize

def _common_fields(item: dict) -> dict:
    """Subset of item config we project into every wiki record."""
    return dict(
        identifier=item['identifier'],
        slug=_slug(item['identifier']),
        display=_humanize(item.get('title_string') or item['identifier']),
        tier=int(item.get('tier') or 1),
        type=item.get('type', ''),
        stack_size=item.get('stack_size'),
        base_price=item.get('base_price'),
        recycle_value=item.get('recycle_value'),
        inv_frame=item.get('inv_frame'),
        durability=item.get('durability'),
        description_string=item.get('description_string'),
        title_string=item.get('title_string'),
    )


def build_ingots(cat: Catalog, ores_by_drop: Dict[str, dict]) -> List[dict]:
    rows = []
    for ident, item in cat.items.items():
        if item.get('type') != 'PROCESSED_ORE' and not ident.endswith('.ingot'):
            continue
        rec = _common_fields(item)
        # Find source ore via recipe whose output0 matches our identifier
        smelt = None
        source = None
        for recipe in cat.recipes:
            if recipe.get('output0') == ident:
                smelt = {
                    'cookTime': recipe.get('cookTime'),
                    'fuelNeeded': recipe.get('fuelNeeded'),
                    'qty': recipe.get('output0qty', 1),
                }
                source_id = recipe.get('input')
                source = ores_by_drop.get(source_id)
                break
        rec['smelt'] = smelt
        rec['smelted_from_identifier'] = source['identifier'] if source else None
        rows.append(rec)
    return rows


def _weapon_stats_for(item: dict, cat: Catalog) -> Optional[dict]:
    """Find weapon stats whose file stem matches this item's file stem."""
    # Find the file stem by reverse lookup on identifier
    target_id = item['identifier']
    for stem, parsed in cat.items_by_file.items():
        if parsed.get('identifier') == target_id:
            return cat.ranged_weapons.get(stem) or cat.melee_weapons.get(stem)
    return None


def build_tools(cat: Catalog, ore_records: List[dict]) -> List[dict]:
    rows = []
    # Map of voxel_tier -> ores it can mine
    ore_by_tier = {}
    for o in ore_records:
        ore_by_tier.setdefault(o['tier'], []).append(o)

    for ident, item in cat.items.items():
        t = item.get('type')
        if t != 'UTILS':
            continue
        rec = _common_fields(item)
        stats = _weapon_stats_for(item, cat)
        rec['weapon_stats'] = stats
        # If it's a mining laser, surface which ores it mines.
        mines = []
        if stats and stats.get('type') == 'MINER':
            vt = stats.get('voxel_tier', 0)
            for o_tier in sorted(ore_by_tier):
                if o_tier <= vt:
                    mines.extend(sorted(ore_by_tier[o_tier], key=lambda o: o['tier']))
        rec['mines_ores'] = mines
        rec['subtype_label'] = ('Mining laser.' if stats and stats.get('type') == 'MINER'
                                  else 'Utility item.')
        rows.append(rec)
    return rows


def build_weapons(cat: Catalog) -> List[dict]:
    rows = []
    for ident, item in cat.items.items():
        t = item.get('type')
        if t not in ('WEAPON_RANGED', 'WEAPON_MELEE'):
            continue
        rec = _common_fields(item)
        rec['weapon_stats'] = _weapon_stats_for(item, cat)
        rows.append(rec)
    return rows


RESOURCE_TYPES = {
    'RESOURCE', 'AMMO', 'CONSUMABLE', 'CREATURE_RESOURCE', 'DARK_RESOURCE',
    'KEY', 'MOD', 'PART', 'WAREZ',
    # Ores themselves and the raw materials they yield (re-listed under
    # Resources for convenience). RAW_ORE already on Ores page, skip here.
}


def build_resources(cat: Catalog) -> List[dict]:
    rows = []
    for ident, item in cat.items.items():
        if item.get('type') in RESOURCE_TYPES:
            rows.append(_common_fields(item))
    return rows


# ----------------------------------------------------------------------- main

def detect_game_path(arg: Optional[str]) -> Path:
    if arg:
        return Path(arg)
    if DEFAULT_GAME_PATH.exists():
        return DEFAULT_GAME_PATH
    raise SystemExit(
        'Could not locate Cubic Odyssey install. Pass --game-path explicitly.\n'
        f'Tried: {DEFAULT_GAME_PATH}'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-path', help='Game install directory (containing data/)')
    ap.add_argument('--out', default=str(WIKI), help='Output wiki dir')
    args = ap.parse_args()

    t0 = time.time()
    game_root = detect_game_path(args.game_path)
    out = Path(args.out)

    print(f'== Cubic Odyssey wiki build')
    print(f'  game:  {game_root}')
    print(f'  out:   {out}')

    print('[1/6] loading catalog…')
    cat = Catalog.load(game_root)
    print(f'       items={len(cat.items)} voxels={len(cat.voxels)} '
          f'recipes={len(cat.recipes)} dists={len(cat.distributions)}')

    print('[2/6] loading distribution metadata…')
    dist_meta = json.loads((HERE / 'world_to_distribution.json').read_text())

    print('[3/6] extracting icons…')
    atlases = _load_atlases(game_root)
    icons_dir = out / 'assets' / 'icons'
    # Slice every item that has an inv_frame, regardless of category. Cheap.
    n_icons = slice_icons(cat.items, atlases, icons_dir)
    print(f'       wrote {n_icons} icons to {icons_dir}')

    print('[4/6] building records…')
    ore_records_objs = build_ore_records(cat, distrib_to_planets={})
    ore_records = [r.to_dict() for r in ore_records_objs]
    ores_by_drop = {r['identifier']: r for r in ore_records}

    ingot_records = build_ingots(cat, ores_by_drop)
    tool_records = build_tools(cat, ore_records)
    weapon_records = build_weapons(cat)
    resource_records = build_resources(cat)
    print(f'       ores={len(ore_records)} ingots={len(ingot_records)} '
          f'tools={len(tool_records)} weapons={len(weapon_records)} '
          f'resources={len(resource_records)}')

    print('[5/6] writing catalog.json…')
    (out / 'data').mkdir(exist_ok=True)
    (out / 'data' / 'catalog.json').write_text(json.dumps({
        'ores': ore_records,
        'ingots': ingot_records,
        'tools': tool_records,
        'weapons': weapon_records,
        'resources': resource_records,
    }, default=str, indent=0, separators=(',', ':')), encoding='utf-8')

    print('[6/6] rendering HTML…')
    # Use mtime of iron voxel as the data version stamp.
    iron_cfg = game_root / 'data' / 'configs' / 'voxels' / 'iron.cfg'
    version = (
        time.strftime('%Y-%m-%d', time.gmtime(iron_cfg.stat().st_mtime))
        if iron_cfg.exists() else 'unknown'
    )
    renderer = WikiRenderer(
        out_dir=out,
        icons_dir=icons_dir,
        dist_meta={k: v for k, v in dist_meta.items() if not k.startswith('_')},
        game_version=version,
    )
    renderer.render(
        ore_records=ore_records,
        ingot_records=ingot_records,
        tool_records=tool_records,
        weapon_records=weapon_records,
        resource_records=resource_records,
    )

    print('[6.5/6] rendering Guides…')
    mb_ctx = motherboard_context(cat, icons_dir)
    mining_ctx = mining_context(cat, ore_records, tool_records, icons_dir)
    trading_ctx = trading_context(cat, ore_records, ingot_records, tool_records,
                                    weapon_records, resource_records)
    renderer.render_guides(
        motherboards_ctx=mb_ctx,
        mining_ctx=mining_ctx,
        trading_ctx=trading_ctx,
        summaries=all_guide_summaries(),
    )

    t1 = time.time()
    print(f'== built in {t1 - t0:.1f}s')
    print(f'   {len(ore_records)} ores + {len(ingot_records)} ingots + '
          f'{len(tool_records)} tools + {len(weapon_records)} weapons + '
          f'{len(resource_records)} resources + 3 guides')
    print(f'   open file://{out}/index.html')


if __name__ == '__main__':
    main()
