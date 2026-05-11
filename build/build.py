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
from extract.gems import build_gem_records, gem_identifiers
from extract.worlds import build_world_records
from extract.enemies import build_enemy_records
from extract.ships import build_ship_records, build_speeder_records
from extract.blocks import build_block_records, block_categories_summary
from extract.guides import (
    motherboard_context, mining_context, trading_context,
    item_damage_context, player_death_context, perks_context,
    gems_context, quests_context, vendor_stock_context,
    all_guide_summaries,
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


def export_voxel_textures(voxels: Dict[str, dict], game_root: Path,
                           out_dir: Path, size: int = 256,
                           thumb_size: int = 128
                           ) -> Dict[str, Dict[str, str]]:
    """Render each voxel as an isometric cube PNG, like the in-game block icon.

    The cube uses three faces: the top, plus left and right sides at 85% / 70%
    brightness for depth. m_defaultTexture is the lookup key — if the base name
    has a "_top" / "_side" companion in data/models/voxels/, those get used for
    the top / sides respectively; otherwise a single face texture fills the
    whole cube. Returns {m_defaultTexture: relative_url}.
    """
    from PIL import Image, ImageDraw, ImageEnhance
    src_dir = game_root / 'data' / 'models' / 'voxels'
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_cache: Dict[str, Optional['Image.Image']] = {}

    def load(stem: str) -> Optional['Image.Image']:
        if stem in tex_cache:
            return tex_cache[stem]
        f = src_dir / f'{stem}.dds'
        img = None
        if f.exists():
            try:
                from PIL import ImageStat
                raw = Image.open(f).convert('RGBA')
                # The DDS alpha channel carries shading / PBR data, not real
                # transparency — every face has alpha in the 120-250 range,
                # which makes the cube body render translucent if we use it
                # as-is. Strip the alpha so the cube interior is fully opaque;
                # the hex corners stay transparent via the polygon mask below.
                r, g, b, _ = raw.split()
                img = Image.merge('RGBA',
                    (r, g, b, Image.new('L', raw.size, 255)))
                # Many _side textures are vertical tile sheets — 1024×1024
                # holding four 1024×256 variant strips, or 1024×4096 holding
                # 16. Sampling the whole image onto a face stacks every
                # variant into bands. Detect tile sheets by checking whether
                # the candidate strips have noticeably different brightnesses
                # (uniform textures pass through unchanged), then take the
                # top strip and tile it vertically to keep the face aspect
                # ratio square.
                w, h = img.size
                if h >= 512 and h % 256 == 0:
                    tile_h = 256
                    n = h // tile_h
                    strips = [img.crop((0, i*tile_h, w, (i+1)*tile_h))
                               for i in range(n)]
                    means = [ImageStat.Stat(s.convert('L')).mean[0]
                              for s in strips]
                    if max(means) - min(means) > 25:
                        top = strips[0]
                        if tile_h < w:
                            tiled = Image.new('RGBA', (w, w))
                            for y in range(0, w, tile_h):
                                tiled.paste(top, (0, y))
                            img = tiled
                        else:
                            img = top
                # Pre-filter the 1024-pixel source down to ~2× face size so the
                # affine transform doesn't have to do a 30× downscale through
                # bilinear sampling (which loses most of the source pixels).
                target = size * 2
                if max(img.size) > target:
                    img.thumbnail((target, target), Image.Resampling.LANCZOS)
            except Exception:
                img = None
        tex_cache[stem] = img
        return img

    def faces_for(default_tex: str):
        # Strip a trailing _top/_side/_bottom so we can probe sibling variants.
        base = default_tex
        for suf in ('_top', '_side', '_bottom'):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        # The base file is conventionally the side (or all-face) texture;
        # the _top sibling overrides only the top when it exists.
        side = load(f'{base}_side') or load(base) or load(default_tex)
        top = load(f'{base}_top') or load(base) or side
        return top, side

    def render(top, side, S=size):
        q = S // 4
        out = Image.new('RGBA', (S, S), (0, 0, 0, 0))

        def paint(tex, affine, polygon, brightness):
            if tex is None:
                return
            t = tex.transform((S, S), Image.AFFINE, affine,
                              resample=Image.Resampling.BILINEAR)
            if brightness != 1.0:
                r, g, b, a = t.split()
                rgb = ImageEnhance.Brightness(
                    Image.merge('RGB', (r, g, b))).enhance(brightness)
                t = Image.merge('RGBA', (*rgb.split(), a))
            mask = Image.new('L', (S, S), 0)
            ImageDraw.Draw(mask).polygon(polygon, fill=255)
            out.paste(t, (0, 0), mask)

        if top is not None:
            W, H = top.size
            paint(top,
                  (W/S, -2*W/S, W/2, H/S, 2*H/S, -H/2),
                  [(0, q), (S//2, 0), (S, q), (S//2, S//2)], 1.0)
        if side is not None:
            W, H = side.size
            paint(side,
                  (2*W/S, 0, -W, H/S, 2*H/S, -3*H/2),
                  [(S//2, S//2), (S, q), (S, 3*q), (S//2, S)], 0.85)
            paint(side,
                  (2*W/S, 0, 0, -H/S, 2*H/S, -H/2),
                  [(0, q), (S//2, S//2), (S//2, S), (0, 3*q)], 0.7)
        return out

    # Keep cubes as RGBA — flattening onto a fixed background colour was a
    # mistake because table rows (var(--bg)) and category cards
    # (var(--bg-card)) use different shades, so any single fill colour
    # leaves a visible rectangle in one of the two contexts.
    thumb_dir = out_dir.parent / 'voxels_thumb'
    thumb_dir.mkdir(parents=True, exist_ok=True)
    urls: Dict[str, Dict[str, str]] = {}
    stems = {v.get('m_defaultTexture') for v in voxels.values()
              if v.get('m_defaultTexture')}
    for stem in stems:
        top, side = faces_for(stem)
        if top is None and side is None:
            continue
        cube = render(top, side, S=size)
        large_path = out_dir / f'{stem}.png'
        cube.save(large_path, 'PNG', optimize=True)
        thumb = cube.resize((thumb_size, thumb_size),
                             Image.Resampling.LANCZOS)
        thumb_path = thumb_dir / f'{stem}.png'
        thumb.save(thumb_path, 'PNG', optimize=True)
        urls[stem] = {
            'large': f'assets/textures/voxels/{stem}.png',
            'thumb': f'assets/textures/voxels_thumb/{stem}.png',
        }
    return urls


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

        # Obtainability
        recipes = cat.recipes_producing(ident)
        randomsets = cat.randomsets_containing(ident)
        npc_users = cat.characters_using_weapon(ident)

        # Skip NPC/critter-only attack profiles when classifying obtainability
        npc_user_names = [u.get('_file') for u in npc_users]

        if recipes:
            recipe = recipes[0]
            rec['obtain'] = {
                'kind': 'craftable',
                'label': 'Craftable',
                'detail': f"Recipe `{recipe.get('_file')}`, requires {recipe.get('neededSkillType')} {recipe.get('neededSkillLevel')}.",
                'recipe_file': recipe.get('_file'),
                'recipe_skill': recipe.get('neededSkillType'),
                'recipe_skill_level': recipe.get('neededSkillLevel'),
            }
        elif randomsets:
            rs_names = [r.get('_file') for r in randomsets]
            rec['obtain'] = {
                'kind': 'loot',
                'label': 'Loot drop',
                'detail': f"Appears in randomset{'s' if len(rs_names) > 1 else ''}: {', '.join(rs_names[:4])}{'…' if len(rs_names) > 4 else ''}.",
                'randomsets': rs_names,
            }
        elif npc_user_names:
            rec['obtain'] = {
                'kind': 'npc',
                'label': 'NPC weapon',
                'detail': f"Used by NPC/mob: {', '.join(npc_user_names[:5])}{'…' if len(npc_user_names) > 5 else ''}. Not directly obtainable by the player from item drops or crafting.",
                'npc_users': npc_user_names,
            }
        else:
            rec['obtain'] = {
                'kind': 'unobtainable',
                'label': 'Unobtainable',
                'detail': 'Not produced by any recipe, not in any random loot set, and not assigned to a character config. May be a debug/unused asset, a quest-script grant, or used by a hardcoded enemy not captured in the standard character configs.',
            }
        rec['obtain_kind'] = rec['obtain']['kind']
        rec['obtain_label'] = rec['obtain']['label']
        rows.append(rec)
    return rows


RESOURCE_TYPES = {
    'RESOURCE', 'AMMO', 'CONSUMABLE', 'CREATURE_RESOURCE', 'DARK_RESOURCE',
    'KEY', 'MOD', 'PART', 'WAREZ',
    # Ores themselves and the raw materials they yield (re-listed under
    # Resources for convenience). RAW_ORE already on Ores page, skip here.
}


def build_resources(cat: Catalog, exclude_ids: set = None) -> List[dict]:
    exclude_ids = exclude_ids or set()
    rows = []
    for ident, item in cat.items.items():
        if ident in exclude_ids:
            continue
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
    texture_urls = export_voxel_textures(
        cat.voxels, game_root, out / 'assets' / 'textures' / 'voxels')
    print(f'       wrote {len(texture_urls)} voxel textures')

    print('[4/6] building records…')
    ore_records_objs = build_ore_records(cat, distrib_to_planets={})
    ore_records = [r.to_dict() for r in ore_records_objs]
    ores_by_drop = {r['identifier']: r for r in ore_records}

    dist_meta_clean = {k: v for k, v in dist_meta.items() if not k.startswith('_')}
    gem_records = build_gem_records(cat, dist_meta_clean)
    world_records = build_world_records(cat, dist_meta_clean)
    enemy_records = build_enemy_records(cat)
    ship_records = build_ship_records(cat)
    speeder_records = build_speeder_records(cat)
    block_records = build_block_records(cat, texture_urls)
    block_categories = block_categories_summary(block_records)

    ingot_records = build_ingots(cat, ores_by_drop)
    tool_records = build_tools(cat, ore_records)
    weapon_records = build_weapons(cat)
    # Gems are RESOURCE type but get their own category — exclude here.
    resource_records = build_resources(cat, exclude_ids=gem_identifiers())
    print(f'       ores={len(ore_records)} gems={len(gem_records)} '
          f'ingots={len(ingot_records)} tools={len(tool_records)} '
          f'weapons={len(weapon_records)} resources={len(resource_records)} '
          f'worlds={len(world_records)} enemies={len(enemy_records)} '
          f'ships={len(ship_records)} speeders={len(speeder_records)}')

    print('[5/6] writing catalog.json…')
    (out / 'data').mkdir(exist_ok=True)
    (out / 'data' / 'catalog.json').write_text(json.dumps({
        'ores': ore_records,
        'gems': gem_records,
        'ingots': ingot_records,
        'tools': tool_records,
        'weapons': weapon_records,
        'resources': resource_records,
        'worlds': world_records,
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
        gem_records=gem_records,
        ingot_records=ingot_records,
        tool_records=tool_records,
        weapon_records=weapon_records,
        resource_records=resource_records,
        world_records=world_records,
        enemy_records=enemy_records,
        ship_records=ship_records,
        speeder_records=speeder_records,
        block_records=block_records,
        block_categories=block_categories,
    )

    print('[6.5/6] rendering Guides…')
    mb_ctx = motherboard_context(cat, icons_dir)
    mining_ctx = mining_context(cat, ore_records, tool_records, icons_dir)
    trading_ctx = trading_context(cat, ore_records, ingot_records, tool_records,
                                    weapon_records, resource_records)
    item_damage_ctx = item_damage_context(cat, icons_dir)
    player_death_ctx = player_death_context(cat, icons_dir)
    perks_ctx = perks_context(cat)
    gems_ctx = gems_context(cat, icons_dir)
    quests_ctx = quests_context(cat)
    vendor_stock_ctx = vendor_stock_context(cat, icons_dir)
    renderer.render_guides(
        motherboards_ctx=mb_ctx,
        mining_ctx=mining_ctx,
        trading_ctx=trading_ctx,
        item_damage_ctx=item_damage_ctx,
        player_death_ctx=player_death_ctx,
        perks_ctx=perks_ctx,
        gems_ctx=gems_ctx,
        quests_ctx=quests_ctx,
        vendor_stock_ctx=vendor_stock_ctx,
        summaries=all_guide_summaries(),
    )

    t1 = time.time()
    print(f'== built in {t1 - t0:.1f}s')
    print(f'   {len(ore_records)} ores + {len(gem_records)} gems + '
          f'{len(ingot_records)} ingots + {len(tool_records)} tools + '
          f'{len(weapon_records)} weapons + {len(resource_records)} resources + '
          f'{len(block_records)} blocks + {len(world_records)} worlds + '
          f'{len(enemy_records)} enemies + {len(ship_records)} ships + '
          f'{len(speeder_records)} speeders + 9 guides')
    print(f'   open file://{out}/index.html')


if __name__ == '__main__':
    main()
