"""World-type records.

Each entry in `data/configs/worldbiomes/X_biomes.cfg` declares a name,
a list of biome regions (temp / altitude bands), and the file in
`data/configs/voxeldistributions/` that controls which voxels and ores
spawn at each Y layer. We collapse those three sources into a per-
world-type record for the wiki.
"""

from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug


def _world_slug(biomes_name: str) -> str:
    return biomes_name.replace('_biomes', '').lower()


def build_world_records(cat: Catalog, dist_meta: dict) -> List[dict]:
    # Voxel name -> wiki url for any ore / gem detail page we render
    voxel_url: Dict[str, str] = {}
    for v in cat.voxels.values():
        name = v.get('name')
        if not name:
            continue
        drop = v.get('m_dropItem')
        if not drop:
            continue
        slug = _slug(drop)
        # Determine which category the voxel's drop maps to
        item = cat.items.get(drop) or {}
        t = item.get('type', '')
        # Gems are RESOURCE but live under gems/
        if drop in {
            'res.diamond', 'res.ruby', 'res.emerald', 'res.sapphire',
            'res.glowing.diamond', 'res.glowing.ruby',
            'res.glowing.emerald', 'res.glowing.sapphire',
        }:
            voxel_url[name] = f'gems/{slug}.html'
        elif t == 'RAW_ORE':
            voxel_url[name] = f'ores/{slug}.html'

    records: List[dict] = []
    for biomes_name, biomes_cfg in cat.biomes.items():
        if biomes_name == 'debug':
            continue
        dist_name = biomes_cfg.get('oreDistributionFile')
        dist = cat.distributions.get(dist_name) or {}
        meta = dist_meta.get(dist_name, {})
        slug = _world_slug(biomes_name)

        # Biome region table
        biome_regions = []
        for b in (biomes_cfg.get('biomes') or []):
            if not isinstance(b, dict):
                continue
            biome_regions.append({
                'name': b.get('biomeName', ''),
                'display': _humanize_biome(b.get('biomeName', '')),
                'startTemp': b.get('startTemp'),
                'endTemp': b.get('endTemp'),
                'startAlt': b.get('startAlt'),
                'endAlt': b.get('endAlt'),
            })

        # Voxel layers + ore summary
        layers = []
        ore_totals: Dict[str, dict] = {}
        layer_cfgs = dist.get('m_layerCfgs') or []
        if isinstance(layer_cfgs, list):
            for li, layer in enumerate(layer_cfgs):
                vox_entries = []
                for e in (layer.get('m_voxels') or []):
                    vox_entries.append({
                        'voxel_name': e.get('m_voxelType', ''),
                        'frequency': e.get('m_frequency', 0),
                        'extent': e.get('m_extent'),
                    })
                ore_entries = []
                for e in (layer.get('m_ores') or []):
                    vn = e.get('m_voxelType', '')
                    freq = e.get('m_frequency', 0) or 0
                    ext = e.get('m_extent')
                    vox = cat.voxels.get(vn) or {}
                    ore_entries.append({
                        'voxel_name': vn,
                        'frequency': freq,
                        'extent': ext,
                        'url': voxel_url.get(vn),
                        'color': vox.get('m_color'),
                    })
                    # Aggregate
                    if freq > 0:
                        agg = ore_totals.setdefault(vn, {
                            'voxel_name': vn,
                            'total_freq': 0,
                            'max_extent': 0,
                            'layer_count': 0,
                            'url': voxel_url.get(vn),
                            'deepest_y': layer.get('m_startY', 0),
                        })
                        agg['total_freq'] += freq
                        if ext:
                            agg['max_extent'] = max(agg['max_extent'], ext)
                        agg['layer_count'] += 1
                        if layer.get('m_startY', 0) < agg['deepest_y']:
                            agg['deepest_y'] = layer.get('m_startY', 0)
                layers.append({
                    'index': li,
                    'startY': layer.get('m_startY'),
                    'endY': layer.get('m_endY'),
                    'singleVoxel': layer.get('m_singleVoxel', 0),
                    'voxels': vox_entries,
                    'ores': ore_entries,
                })

        ore_summary = sorted(ore_totals.values(),
                              key=lambda r: (-r['total_freq'], r['voxel_name']))

        records.append({
            'slug': slug,
            'display': meta.get('label', biomes_name.replace('_', ' ').title()),
            'short_label': meta.get('short', biomes_name.replace('_biomes', '').title()),
            'biomes_name': biomes_name,
            'distribution_name': dist_name,
            'description': meta.get('description', ''),
            'planets': meta.get('planets') or [],
            'biome_regions': biome_regions,
            'biome_region_count': len(biome_regions),
            'layers': layers,
            'layer_count': len(layers),
            'ore_summary': ore_summary,
            'ore_summary_count': len(ore_summary),
        })

    # Sort: those with named planets first, then alphabetic
    records.sort(key=lambda r: (-len(r['planets']), r['display']))
    return records


def _humanize_biome(name: str) -> str:
    """`crystalline_arctic_mountains` -> `Arctic mountains` (drop the
    world-type prefix; it's redundant on the world's own page)."""
    if not name:
        return ''
    parts = name.split('_')
    # Drop a known world-type prefix if present
    prefixes = {'crystalline', 'scorched', 'barren', 'shroomy', 'slimy',
                'xeno', 'majestic', 'oceanic', 'earth'}
    if parts and parts[0] in prefixes:
        parts = parts[1:]
    return ' '.join(p.capitalize() if i == 0 else p for i, p in enumerate(parts))
