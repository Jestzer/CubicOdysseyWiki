"""Block (voxel) records.

The game ships 291 voxels in 19 m_category buckets — ores, building
blocks, glass, water, ancient artefacts, etc. This extractor produces a
record per voxel and groups them by category so the wiki can show a
Blocks page sorted by what each voxel is for.
"""

from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug


CATEGORY_LABELS: Dict[str, str] = {
    'E_VCAT_ORES':              'Ores',
    'E_VCAT_GLOWING_ORES':      'Glowing ores',
    'E_VCAT_STONE':             'Stone',
    'E_VCAT_DIRT':              'Dirt',
    'E_VCAT_SAND':              'Sand',
    'E_VCAT_SNOW':              'Snow',
    'E_VCAT_ICE':               'Ice',
    'E_VCAT_WATER':             'Water',
    'E_VCAT_BIOME_SURFACE':     'Biome surface',
    'E_VCAT_BIOME_SUBSURFACE':  'Biome subsurface',
    'E_VCAT_TRUNK':             'Tree trunks',
    'E_VCAT_LEAVES':            'Foliage',
    'E_VCAT_BUILDING':          'Building',
    'E_VCAT_FLOOR':             'Floors',
    'E_VCAT_WALL':              'Walls',
    'E_VCAT_GLASS':             'Glass',
    'E_VCAT_MATERIAL':          'Material',
    'E_VCAT_ARMOR':             'Armor',
    'E_VCAT_ANCIENT':           'Ancient',
}

# Surface-up category ordering for the index
CATEGORY_ORDER = [
    'E_VCAT_BIOME_SURFACE', 'E_VCAT_BIOME_SUBSURFACE',
    'E_VCAT_DIRT', 'E_VCAT_SAND', 'E_VCAT_SNOW', 'E_VCAT_ICE', 'E_VCAT_WATER',
    'E_VCAT_TRUNK', 'E_VCAT_LEAVES',
    'E_VCAT_STONE',
    'E_VCAT_ORES', 'E_VCAT_GLOWING_ORES',
    'E_VCAT_BUILDING', 'E_VCAT_FLOOR', 'E_VCAT_WALL',
    'E_VCAT_GLASS', 'E_VCAT_ARMOR', 'E_VCAT_ANCIENT',
    'E_VCAT_MATERIAL',
]


def _link_for_drop(drop_id: Optional[str], cat: Catalog) -> Optional[str]:
    if not drop_id:
        return None
    item = cat.items.get(drop_id)
    if not item:
        return None
    t = item.get('type', '')
    slug = _slug(drop_id)
    GEM_IDS = {'res.diamond','res.ruby','res.emerald','res.sapphire',
                'res.glowing.diamond','res.glowing.ruby',
                'res.glowing.emerald','res.glowing.sapphire'}
    if drop_id in GEM_IDS:
        return f'gems/{slug}.html'
    if t == 'RAW_ORE':
        return f'ores/{slug}.html'
    if t == 'PROCESSED_ORE' or drop_id.endswith('.ingot'):
        return f'ingots/{slug}.html'
    if t in {'RESOURCE','PART','MOD'}:
        return f'resources/{slug}.html'
    return None


def build_block_records(cat: Catalog,
                          texture_urls: Optional[Dict[str, str]] = None
                          ) -> List[dict]:
    texture_urls = texture_urls or {}
    records: List[dict] = []
    for vname, v in cat.voxels.items():
        cat_raw = v.get('m_category', '')
        drop_id = v.get('m_dropItem')
        tex = v.get('m_defaultTexture')
        records.append({
            'name': vname,
            'slug': _slug(vname).replace(' ', '_'),
            'display': vname,
            'category_raw': cat_raw,
            'category_label': CATEGORY_LABELS.get(cat_raw, cat_raw.replace('E_VCAT_', '').title().replace('_', ' ') if cat_raw else 'Other'),
            'category_order': CATEGORY_ORDER.index(cat_raw) if cat_raw in CATEGORY_ORDER else 99,
            'tier': v.get('m_tier'),
            'mine_unit': v.get('m_mineUnit'),
            'color': v.get('m_color'),
            'drop_item': drop_id,
            'drop_url': _link_for_drop(drop_id, cat),
            'drop_display': _humanize(cat.items.get(drop_id, {}).get('title_string') or drop_id) if drop_id and cat.items.get(drop_id) else None,
            'transparent': v.get('m_transparent', 0),
            'reg_ore': v.get('m_regOre', 0),
            'default_texture': tex,
            'texture_url': texture_urls.get(tex) if tex else None,
            'title_str_id': v.get('titleStrId'),
        })

    records.sort(key=lambda r: (r['category_order'],
                                  -(r['tier'] or 0),
                                  r['display']))
    return records


def block_categories_summary(records: List[dict]) -> List[dict]:
    """Return one row per category for the overview page."""
    buckets: Dict[str, List[dict]] = {}
    for r in records:
        buckets.setdefault(r['category_raw'], []).append(r)
    out = []
    for cat_raw, rs in buckets.items():
        out.append({
            'category_raw': cat_raw,
            'category_label': rs[0]['category_label'],
            'category_order': rs[0]['category_order'],
            'count': len(rs),
            'sample_textures': [r['texture_url'] for r in rs[:6] if r.get('texture_url')],
            'sample_colors': [r['color'] for r in rs[:6] if r['color']],
            'sample_names': [r['display'] for r in rs[:5]],
        })
    out.sort(key=lambda r: r['category_order'])
    return out
