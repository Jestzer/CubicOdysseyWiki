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
    from PIL import ImageStat
    variant_cache: Dict[str, List['Image.Image']] = {}

    def load_raw(stem: str) -> Optional['Image.Image']:
        f = src_dir / f'{stem}.dds'
        if not f.exists():
            return None
        try:
            raw = Image.open(f).convert('RGBA')
        except Exception:
            return None
        # The DDS alpha channel carries shading / PBR data, not real
        # transparency — every face has alpha in the 120-250 range, which
        # makes the cube body render translucent if used as-is. Force alpha
        # to 255 so the cube interior is fully opaque; the hex corners stay
        # transparent via the polygon mask in render().
        r, g, b, _ = raw.split()
        return Image.merge('RGBA',
            (r, g, b, Image.new('L', raw.size, 255)))

    def variants_of(stem: str) -> List['Image.Image']:
        """Return a list of face-ready textures for one DDS.

        A few DDS sources are genuine vertical tile sheets — e.g.
        shroomy_tropical_turf_side is 1024×1024 with a hard band of dirt
        over a hard band of turf, and hull_plate_5_side stacks distinct
        panel variants. But others (radium.dds, snow.dds) are *coherent*
        textures whose brightness happens to vary smoothly across rows;
        a naive brightness check misclassifies them as tile sheets and
        crops out 3/4 of the texture content.

        Distinguish the two cases by comparing the average per-row colour
        delta AT strip boundaries vs INSIDE strips: a real tile sheet
        has sharp jumps every 256 rows, a coherent texture varies
        smoothly. If we detect a tile sheet, return its strips as
        variants; otherwise return the full image as a single variant.
        """
        if stem in variant_cache:
            return variant_cache[stem]
        img = load_raw(stem)
        if img is None:
            variant_cache[stem] = []
            return []
        w, h = img.size
        result: List['Image.Image'] = [img]
        if h >= 256 and w >= 256:
            # A tile sheet has visibly different content top vs bottom (the
            # snow_side and biome turfs put dirt above turf/snow; hull
            # plates stack lit panels above white). The mean RGB of the
            # top vs bottom halves differs by 100+ in those cases. A
            # coherent texture (radium, snow, aluminium) has similar mean
            # colour in both halves — the local features may differ but
            # the global content is uniform.
            top_half = img.crop((0, 0, w, h // 2)).convert('RGB')
            bot_half = img.crop((0, h // 2, w, h)).convert('RGB')
            tm = ImageStat.Stat(top_half).mean
            bm = ImageStat.Stat(bot_half).mean
            color_delta = sum(abs(tm[i] - bm[i]) for i in range(3))
            if color_delta > 60:
                # It's a tile sheet. Find the row where the brightness
                # gradient is sharpest using a sliding window (the actual
                # transition can be many rows wide — gradual dirt → turf
                # — and at any row, not just 256-aligned).
                gray = img.convert('L')
                row_means = [ImageStat.Stat(
                    gray.crop((0, y, w, y+1))).mean[0] for y in range(h)]
                window = max(16, h // 32)
                best_y, best_delta = h // 2, 0.0
                cum_sums = [0.0]
                for v in row_means:
                    cum_sums.append(cum_sums[-1] + v)
                for y in range(window, h - window):
                    prev_mean = (cum_sums[y] - cum_sums[y - window]) / window
                    next_mean = (cum_sums[y + window] - cum_sums[y]) / window
                    d = abs(next_mean - prev_mean)
                    if d > best_delta:
                        best_delta = d
                        best_y = y
                if best_delta > 15:
                    # Shift the cut a little past the steepest gradient so
                    # both strips end up clear of the transition zone —
                    # snow_side's dirt-to-snow band tails into the snow
                    # strip's top rows and leaves dark dirt specks visible
                    # on the cube's top edges if the cut sits right on the
                    # gradient.
                    margin = h // 40
                    cut = min(h - 32, best_y + margin)
                    strips: List['Image.Image'] = []
                    for top_y, bot_y in ((0, cut - margin),
                                          (cut, h)):
                        if bot_y - top_y >= 32:
                            strips.append(img.crop((0, top_y, w, bot_y)))
                    if len(strips) >= 2:
                        result = strips
        # Make every variant square by *mirror-tiling* the strip along
        # its short axis. Plain tiling leaves a seam where the strip's
        # bottom row meets the next copy's top row — visible on textures
        # with any directional content (alien_grass turf). Mirror-tiling
        # alternates flipped copies, so every boundary is bottom↔bottom or
        # top↔top — matching edges by construction. Tiling instead of
        # centre-cropping restores the source pixel count so the SIDE face
        # gets the same heavy 4× LANCZOS pre-thumbnail as the TOP face,
        # avoiding the pixelated-side / smooth-top mismatch.
        squared: List['Image.Image'] = []
        for v in result:
            vw, vh = v.size
            if vw == vh:
                squared.append(v)
                continue
            if vw > vh:
                flipped = v.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                copies = (vw + vh - 1) // vh
                tiled = Image.new('RGBA', (vw, vh * copies))
                for i in range(copies):
                    tiled.paste(v if i % 2 == 0 else flipped, (0, i * vh))
                squared.append(tiled.crop((0, 0, vw, vw)))
            else:
                flipped = v.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                copies = (vh + vw - 1) // vw
                tiled = Image.new('RGBA', (vw * copies, vh))
                for i in range(copies):
                    tiled.paste(v if i % 2 == 0 else flipped, (i * vw, 0))
                squared.append(tiled.crop((0, 0, vh, vh)))
        # Pre-filter each variant to the cube output size. PIL's affine
        # transform scales its sampling kernel by the affine's `a` factor,
        # so a side face with a=2W/S returns OOB-fill (transparent) along
        # the inside edge when the texture is bigger than the output. With
        # W=S, the kernel stays a 2×2 box that the replicate-padding can
        # cover cheaply.
        target = size
        scaled: List['Image.Image'] = []
        for v in squared:
            if max(v.size) > target:
                v = v.copy()
                v.thumbnail((target, target), Image.Resampling.LANCZOS)
            scaled.append(v)
        variant_cache[stem] = scaled
        return scaled

    def faces_for(default_tex: str):
        # Strip a trailing _top/_side/_bottom so we can probe sibling variants.
        base = default_tex
        for suf in ('_top', '_side', '_bottom'):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        # The base file is conventionally the side (or all-face) texture;
        # the _top sibling overrides only the top when it exists.
        side = variants_of(f'{base}_side') or variants_of(base) or variants_of(default_tex)
        top = variants_of(f'{base}_top') or variants_of(base) or side
        return top, side

    def render(top, side, S=size):
        q = S // 4
        out = Image.new('RGBA', (S, S), (0, 0, 0, 0))

        def paint(tex, affine, polygon, brightness):
            if tex is None:
                return
            # Pad the texture by replicating its edge pixels before the
            # affine. Bilinear sampling at the cube's face seams hits texture
            # coordinates exactly at the source edges (e.g. x=W or y=H); with
            # the default fillcolor=(0,0,0,0) PIL averages those samples
            # against transparent black, leaving dark hairline pixels along
            # the internal cube seams. Replicate padding makes the OOB
            # samples equal to the edge values, so the bilinear average
            # produces the correct edge colour.
            # pad needs to cover the polygon overlap (ov below) PLUS the
            # outline/line stroke width PLUS PIL's bilinear kernel width
            # (a×1 for affine `a` factor). With ov=2 and a=2 on the side
            # faces, the kernel needs to land at most at input x = 270 for
            # output x = 131; padded width must be ≥ 272, so pad ≥ 8.
            pad = 8
            tw, th = tex.size
            pt = Image.new('RGBA', (tw + 2*pad, th + 2*pad))
            pt.paste(tex, (pad, pad))
            pt.paste(tex.crop((0, 0, tw, 1)).resize((tw, pad)),
                     (pad, 0))
            pt.paste(tex.crop((0, th-1, tw, th)).resize((tw, pad)),
                     (pad, th + pad))
            pt.paste(tex.crop((0, 0, 1, th)).resize((pad, th)),
                     (0, pad))
            pt.paste(tex.crop((tw-1, 0, tw, th)).resize((pad, th)),
                     (tw + pad, pad))
            pt.paste(tex.crop((0, 0, 1, 1)).resize((pad, pad)),
                     (0, 0))
            pt.paste(tex.crop((tw-1, 0, tw, 1)).resize((pad, pad)),
                     (tw + pad, 0))
            pt.paste(tex.crop((0, th-1, 1, th)).resize((pad, pad)),
                     (0, th + pad))
            pt.paste(tex.crop((tw-1, th-1, tw, th)).resize((pad, pad)),
                     (tw + pad, th + pad))
            a, b, c, d, e, f = affine
            affine = (a, b, c + pad, d, e, f + pad)
            # BILINEAR samples 4 source pixels per output pixel — gives the
            # smooth shaded look the in-game block icons have.
            t = pt.transform((S, S), Image.AFFINE, affine,
                             resample=Image.Resampling.BILINEAR)
            if brightness != 1.0:
                r, g, b, a = t.split()
                rgb = ImageEnhance.Brightness(
                    Image.merge('RGB', (r, g, b))).enhance(brightness)
                t = Image.merge('RGBA', (*rgb.split(), a))
            mask = Image.new('L', (S, S), 0)
            ImageDraw.Draw(mask).polygon(polygon, fill=255, outline=255)
            out.paste(t, (0, 0), mask)

        # Natural face polygons with no overlap. Each polygon's fill +
        # outline covers x=128 (the centre vertical seam) and the two
        # diagonals exactly; the last-paint-wins order resolves the
        # one-pixel-shared boundary deterministically.
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
        top_variants, side_variants = faces_for(stem)
        if not top_variants and not side_variants:
            continue
        # Pair variants: cube i uses top[i] and side[i], clipping to the
        # last available variant when one side has fewer than the other.
        n = max(len(top_variants), len(side_variants), 1)
        # The last variant is the canonical face (highest-detail / "freshest"
        # frame; for radium-style ore sheets this is the bottom strip with
        # the cleanest texture). The hero, index thumb, and category cards
        # all source from it; intermediate variants stay accessible via the
        # gallery on the detail page.
        canonical_idx = n - 1
        variant_urls: List[str] = []
        for i in range(n):
            top_i = top_variants[min(i, len(top_variants)-1)] if top_variants else None
            side_i = side_variants[min(i, len(side_variants)-1)] if side_variants else None
            cube = render(top_i, side_i, S=size)
            if i == canonical_idx:
                large_path = out_dir / f'{stem}.png'
                cube.save(large_path, 'PNG', optimize=True)
                variant_urls.append(f'assets/textures/voxels/{stem}.png')
                thumb = cube.resize((thumb_size, thumb_size),
                                     Image.Resampling.LANCZOS)
                thumb.save(thumb_dir / f'{stem}.png', 'PNG', optimize=True)
            else:
                v_path = out_dir / f'{stem}__v{i+1}.png'
                cube.save(v_path, 'PNG', optimize=True)
                variant_urls.append(f'assets/textures/voxels/{stem}__v{i+1}.png')
        urls[stem] = {
            'large': f'assets/textures/voxels/{stem}.png',
            'thumb': f'assets/textures/voxels_thumb/{stem}.png',
            'variants': variant_urls,
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


def _classify_obtain(ident: str, cat: Catalog) -> dict:
    """Classify how the player obtains an equippable item (weapon/tool).

    Returns a dict with keys ``kind`` (craftable | loot | npc | unobtainable),
    ``label``, and a longer ``detail`` string; also includes the supporting
    identifiers (recipe_file, randomsets, npc_users) where applicable so
    detail pages can render them.
    """
    recipes = cat.recipes_producing(ident)
    if recipes:
        recipe = recipes[0]
        return {
            'kind': 'craftable',
            'label': 'Craftable',
            'detail': f"Recipe `{recipe.get('_file')}`, requires {recipe.get('neededSkillType')} {recipe.get('neededSkillLevel')}.",
            'recipe_file': recipe.get('_file'),
            'recipe_skill': recipe.get('neededSkillType'),
            'recipe_skill_level': recipe.get('neededSkillLevel'),
        }
    randomsets = cat.randomsets_containing(ident)
    if randomsets:
        rs_names = [r.get('_file') for r in randomsets]
        return {
            'kind': 'loot',
            'label': 'Loot drop',
            'detail': f"Appears in randomset{'s' if len(rs_names) > 1 else ''}: {', '.join(rs_names[:4])}{'…' if len(rs_names) > 4 else ''}.",
            'randomsets': rs_names,
        }
    npc_users = cat.characters_using_weapon(ident)
    if npc_users:
        npc_user_names = [u.get('_file') for u in npc_users]
        return {
            'kind': 'npc',
            'label': 'NPC weapon',
            'detail': f"Used by NPC/mob: {', '.join(npc_user_names[:5])}{'…' if len(npc_user_names) > 5 else ''}. Not directly obtainable by the player from item drops or crafting.",
            'npc_users': npc_user_names,
        }
    return {
        'kind': 'unobtainable',
        'label': 'Unobtainable',
        'detail': 'Not produced by any recipe, not in any random loot set, and not assigned to a character config. May be a debug/unused asset, a quest-script grant, or used by a hardcoded enemy not captured in the standard character configs.',
    }


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
        rec['obtain'] = _classify_obtain(ident, cat)
        rec['obtain_kind'] = rec['obtain']['kind']
        rec['obtain_label'] = rec['obtain']['label']
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
        rec['obtain'] = _classify_obtain(ident, cat)
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


# ------------------------------------------------------- planet→distribution

_ROMAN = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII'}


def _planet_display(stem: str) -> Optional[str]:
    """`bardwell_01` → `Bardwell I`, `earth_planet` → `Earth`. Returns None
    for debug/test stems we don't want to surface."""
    if stem == 'earth_planet':
        return 'Earth'
    if stem.upper() == stem:  # TEST_01 etc.
        return None
    if '_' not in stem:
        return stem.title()
    name, tail = stem.rsplit('_', 1)
    if tail.isdigit():
        n = int(tail)
        return f'{name.title()} {_ROMAN.get(n, str(n))}'
    return stem.replace('_', ' ').title()


def _attach_planets_from_catalog(dist_meta: dict, cat) -> None:
    """Walk `data/configs/worlds/*.cfg`, follow each world's `m_biomesSetCfg`
    (or `m_isEarthLike`) to its biome family, then to its
    `oreDistributionFile`. Overwrite `dist_meta[<dist>]['planets']` with the
    derived list so the wiki reflects the actual game data instead of the
    best-effort JSON hardcode."""
    by_dist: Dict[str, List[str]] = {k: [] for k in dist_meta if not k.startswith('_')}
    for stem, wcfg in cat.worlds.items():
        if not isinstance(wcfg, dict):
            continue
        biomes_name = wcfg.get('m_biomesSetCfg')
        if not biomes_name and wcfg.get('m_isEarthLike') in (True, 'true', 1):
            biomes_name = 'earth_biomes'
        if not biomes_name:
            continue
        biomes_cfg = cat.biomes.get(biomes_name) or {}
        dist_name = biomes_cfg.get('oreDistributionFile')
        if not dist_name or dist_name not in by_dist:
            continue
        display = _planet_display(stem)
        if display and display not in by_dist[dist_name]:
            by_dist[dist_name].append(display)
    for dname, planets in by_dist.items():
        dist_meta.setdefault(dname, {})['planets'] = sorted(planets)


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
    _attach_planets_from_catalog(dist_meta, cat)

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
