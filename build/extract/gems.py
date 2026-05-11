"""Gem records — Diamond / Ruby / Emerald / Sapphire and their Glowing
variants. These are item type RESOURCE in the catalog (not RAW_ORE), but
spawn as voxels and behave like ores.  We surface them as their own wiki
category so the location data, mining tier, and co-occurrence with other
gems all live on one page per gem.
"""

from pathlib import Path
from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug


GEM_VOXEL_BY_IDENT: Dict[str, str] = {
    'res.diamond':           'Diamond',
    'res.ruby':              'Ruby',
    'res.emerald':           'Emerald',
    'res.sapphire':          'Sapphire',
    'res.glowing.diamond':   'Glowing Diamond',
    'res.glowing.ruby':      'Glowing Ruby',
    'res.glowing.emerald':   'Glowing Emerald',
    'res.glowing.sapphire':  'Glowing Sapphire',
}

# Reverse map: voxel name -> identifier, for co-occurrence display
VOXEL_TO_IDENT: Dict[str, str] = {v: k for k, v in GEM_VOXEL_BY_IDENT.items()}


def gem_identifiers() -> set:
    return set(GEM_VOXEL_BY_IDENT.keys())


def build_gem_records(cat: Catalog, dist_meta: dict) -> List[dict]:
    # First pass: precompute which gem voxels are present in each (dist, layer)
    layer_gem_voxels: Dict[tuple, set] = {}
    layer_y_range: Dict[tuple, tuple] = {}
    for dname, dist in cat.distributions.items():
        layers = dist.get('m_layerCfgs') or []
        if not isinstance(layers, list):
            continue
        for li, layer in enumerate(layers):
            names = set()
            for e in (layer.get('m_ores') or []):
                vt = e.get('m_voxelType')
                if vt in VOXEL_TO_IDENT:
                    names.add(vt)
            if names:
                key = (dname, li)
                layer_gem_voxels[key] = names
                layer_y_range[key] = (layer.get('m_startY', 0), layer.get('m_endY', 0))

    # For each distribution, identify the layer with the lowest m_startY that
    # actually contains a gem — that's the "deepest" gem-bearing layer.
    deepest_layer_idx: Dict[str, int] = {}
    deepest_layer_y: Dict[str, int] = {}
    for (dname, li), _ in layer_gem_voxels.items():
        ys = layer_y_range[(dname, li)][0]
        if dname not in deepest_layer_idx or ys < deepest_layer_y[dname]:
            deepest_layer_idx[dname] = li
            deepest_layer_y[dname] = ys

    # Second pass: per-gem records
    records: List[dict] = []
    for ident, voxel_name in GEM_VOXEL_BY_IDENT.items():
        item = cat.items.get(ident)
        if not item:
            continue
        voxel = cat.voxels.get(voxel_name) or {}

        locations: List[dict] = []
        for dname, dist in cat.distributions.items():
            if dname in ('debug', 'default'):
                continue
            layers = dist.get('m_layerCfgs') or []
            if not isinstance(layers, list):
                continue
            for li, layer in enumerate(layers):
                for e in (layer.get('m_ores') or []):
                    if e.get('m_voxelType') != voxel_name:
                        continue
                    co_voxels = layer_gem_voxels.get((dname, li), set()) - {voxel_name}
                    co_records = []
                    for vn in sorted(co_voxels):
                        co_ident = VOXEL_TO_IDENT.get(vn)
                        co_records.append({
                            'voxel_name': vn,
                            'identifier': co_ident,
                            'slug': _slug(co_ident) if co_ident else _slug(vn),
                            'display': _humanize(
                                cat.items.get(co_ident, {}).get('title_string') or co_ident or vn
                            ),
                        })
                    meta = dist_meta.get(dname, {})
                    locations.append({
                        'distribution': dname,
                        'world_type': meta.get('label', dname),
                        'world_short': meta.get('short', ''),
                        'planets': meta.get('planets') or [],
                        'layer_index': li,
                        'y_start': layer.get('m_startY', 0),
                        'y_end': layer.get('m_endY', 0),
                        'frequency': e.get('m_frequency', 0),
                        'extent': e.get('m_extent'),
                        'co_occurring': co_records,
                        'is_deepest': deepest_layer_idx.get(dname) == li,
                    })
        # Sort: deepest first (lowest y_start), then by frequency desc
        locations.sort(key=lambda l: (l['y_start'], -l['frequency']))

        # Required mining laser tier from voxel tier
        tier = voxel.get('m_tier') or item.get('tier') or 5

        records.append({
            'identifier': ident,
            'slug': _slug(ident),
            'display': _humanize(item.get('title_string') or ident),
            'voxel_name': voxel_name,
            'tier': tier,
            'is_glowing': 'glowing' in ident.lower(),
            'mine_unit': voxel.get('m_mineUnit'),
            'color': voxel.get('m_color'),
            'base_price': item.get('base_price'),
            'base_demand': item.get('base_demand'),
            'recycle_value': item.get('recycle_value'),
            'stack_size': item.get('stack_size'),
            'inv_frame': item.get('inv_frame'),
            'description_string': item.get('description_string'),
            'type': item.get('type', 'RESOURCE'),
            'locations': locations,
            'required_laser_file': _required_laser_file(tier),
            'required_laser': _required_laser_id(tier),
        })

    return records


def _required_laser_file(tier: int) -> Optional[str]:
    """Return the lowest-id mining laser whose voxel_tier >= ore tier.
    Hardcoded from the rangedweapons data: lasers 0..7 have voxel tiers
    1,2,3,4,5,6,7,7."""
    table = [
        ('MINING_LASER_0', 1),
        ('MINING_LASER_1', 2),
        ('MINING_LASER_2', 3),
        ('MINING_LASER_3', 4),
        ('MINING_LASER_4', 5),
        ('MINING_LASER_5', 6),
        ('MINING_LASER_6', 7),
    ]
    for name, vt in table:
        if vt >= tier:
            return name
    return None


def _required_laser_id(tier: int) -> Optional[str]:
    f = _required_laser_file(tier)
    if not f:
        return None
    return f.lower().replace('mining_laser_', 'wep.mining_laser.')
