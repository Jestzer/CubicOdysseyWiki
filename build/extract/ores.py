"""Build enriched ore records from the catalog.

For every ore item (type == RAW_ORE) we resolve:
  - the source voxel (block) that drops it, if any
  - the required mining-laser tier
  - the furnace recipe + resulting ingot
  - every (planet, biome, depth) where the voxel spawns
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from extract.catalog import Catalog


@dataclass
class OreLocation:
    distribution: str            # voxel-distribution filename (no ext)
    planets: List[str]           # planet display names that use this distribution
    layer_index: int             # 0-based
    y_start: int
    y_end: int
    frequency: int               # m_frequency
    extent: Optional[int] = None # m_extent (vein size hint)
    role: str = 'ore'            # 'ore' or 'voxel' (where in the layer it appears)


@dataclass
class OreRecord:
    identifier: str              # res.iron.ore
    slug: str                    # iron_ore
    display: str                 # "Iron Ore"
    tier: int
    is_glowing: bool
    voxel_name: Optional[str]    # "Iron" if voxel-backed
    voxel: Optional[dict]
    item: dict
    mine_unit: Optional[float]   # voxel hardness
    color: Optional[List[int]]   # RGB(A) from voxel
    inv_frame: Optional[int]
    base_price: Any
    recycle_value: Any
    stack_size: Any
    description_string: Optional[str]
    required_laser: Optional[str]      # 'wep.mining_laser.0' if known
    required_laser_file: Optional[str] # 'MINING_LASER_0'
    smelt: Optional[dict]              # {ingot, cookTime, fuelNeeded, qty}
    ingot_identifier: Optional[str]
    locations: List[OreLocation] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['locations'] = [asdict(loc) for loc in self.locations]
        d.pop('voxel', None)
        d.pop('item', None)
        d.pop('raw', None)
        return d


# Tool tier table, derived once per build run.
def _mining_laser_table(cat: Catalog) -> List[dict]:
    out = []
    for fname, w in cat.ranged_weapons.items():
        if w.get('type') == 'MINER':
            out.append({
                'file': fname,
                'identifier': f"wep.mining_laser.{fname.rsplit('_', 1)[-1]}",
                'voxel_tier': w.get('voxel_tier', 0),
            })
    # sort by voxel_tier asc, then by file (lower laser id first for same tier)
    out.sort(key=lambda r: (r['voxel_tier'], r['file']))
    return out


def _required_laser(tier: int, table: List[dict]) -> Optional[dict]:
    """Return the lowest-id mining laser with voxel_tier >= ore tier."""
    candidates = [r for r in table if r['voxel_tier'] >= tier]
    if not candidates:
        return None
    return candidates[0]


def _voxel_for_drop(drop_id: str, cat: Catalog) -> Optional[dict]:
    for v in cat.voxels.values():
        if v.get('m_dropItem') == drop_id:
            return v
    return None


def _slug(identifier: str) -> str:
    return identifier.replace('.', '_').replace(' ', '_').lower()


def _humanize(token: str) -> str:
    """Turn STR_GLOWING_IRON_ORE / res.iron.ore / wep.mining_laser.1 into
    a passable display name. The localization .str files are not decoded yet."""
    if not token:
        return ''
    if token.startswith('STR_'):
        token = token[4:]
    token = token.replace('_DESC', '')
    parts = [p for p in token.replace('.', ' ').replace('_', ' ').split() if p]
    cleaned = []
    skip_first = {'res', 'wep', 'cloth', 'ship', 'speeder', 'dpl', 'spn', 'comp'}
    for i, p in enumerate(parts):
        lp = p.lower()
        if i == 0 and lp in skip_first:
            continue
        if lp == 'glowing':
            cleaned.append('Glowing')
        elif lp == 'ore':
            cleaned.append('Ore')
        elif lp == 'ingot':
            cleaned.append('Ingot')
        elif lp == 'cell':
            cleaned.append('Cell')
        elif lp == 'rare':
            # 'res.rare.antimatter' → drop the 'rare' tier marker
            continue
        elif lp.isdigit():
            cleaned.append(p)
        else:
            cleaned.append(p.capitalize())
    return ' '.join(cleaned) if cleaned else token


def _locations_for_voxel(voxel_name: str,
                         distributions: Dict[str, dict],
                         distrib_to_planets: Dict[str, List[str]]
                         ) -> List[OreLocation]:
    out: List[OreLocation] = []
    for dname, dist in distributions.items():
        layers = dist.get('m_layerCfgs') or []
        if not isinstance(layers, list):
            continue
        for li, layer in enumerate(layers):
            for role_key, role_name in (('m_ores', 'ore'), ('m_voxels', 'voxel')):
                entries = layer.get(role_key) or []
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if entry.get('m_voxelType') == voxel_name:
                        out.append(OreLocation(
                            distribution=dname,
                            planets=distrib_to_planets.get(dname, []),
                            layer_index=li,
                            y_start=layer.get('m_startY', 0),
                            y_end=layer.get('m_endY', 0),
                            frequency=entry.get('m_frequency', 0),
                            extent=entry.get('m_extent'),
                            role=role_name,
                        ))
    return out


def build_ore_records(cat: Catalog,
                       distrib_to_planets: Dict[str, List[str]]
                       ) -> List[OreRecord]:
    laser_table = _mining_laser_table(cat)
    records: List[OreRecord] = []

    # Drive off RAW_ORE items so we cover both voxel-backed and Glowing variants.
    raw_ore_items = {ident: it for ident, it in cat.items.items()
                     if it.get('type') == 'RAW_ORE'}

    for ident, item in sorted(raw_ore_items.items()):
        voxel = _voxel_for_drop(ident, cat)
        voxel_name = voxel.get('name') if voxel else item.get('voxelSource')
        if voxel_name and not voxel:
            voxel = cat.voxel_by_name(voxel_name)

        tier = (voxel.get('m_tier') if voxel else None) or item.get('tier') or 1
        recipe = cat.recipe_for_input(ident)
        laser = _required_laser(tier, laser_table)
        is_glowing = 'glowing' in ident.lower() or ident.startswith('res.rare.')

        display = _humanize(item.get('title_string') or ident)
        rec = OreRecord(
            identifier=ident,
            slug=_slug(ident),
            display=display,
            tier=tier,
            is_glowing=is_glowing,
            voxel_name=voxel_name,
            voxel=voxel,
            item=item,
            mine_unit=(voxel.get('m_mineUnit') if voxel else None),
            color=(voxel.get('m_color') if voxel else None),
            inv_frame=item.get('inv_frame'),
            base_price=item.get('base_price'),
            recycle_value=item.get('recycle_value'),
            stack_size=item.get('stack_size'),
            description_string=item.get('description_string'),
            required_laser=(laser['identifier'] if laser else None),
            required_laser_file=(laser['file'] if laser else None),
            smelt=({
                'cookTime': recipe.get('cookTime'),
                'fuelNeeded': recipe.get('fuelNeeded'),
                'output': recipe.get('output0'),
                'qty': recipe.get('output0qty', 1),
            } if recipe else None),
            ingot_identifier=(recipe.get('output0') if recipe else None),
            locations=(_locations_for_voxel(voxel_name, cat.distributions,
                                             distrib_to_planets) if voxel_name else []),
            raw={},
        )
        records.append(rec)

    return records


if __name__ == '__main__':
    import json
    from pathlib import Path
    from extract.catalog import Catalog
    GAME = Path('/run/media/james/SSD/Program Files (x86)/Steam/steamapps/common/Cubic Odyssey')
    cat = Catalog.load(GAME)
    records = build_ore_records(cat, distrib_to_planets={'earth_voxels': ['Earth']})
    print(f'Built {len(records)} ore records')
    for r in records[:5]:
        print(f'\n{r.identifier}  ({r.display})')
        print(f'  tier={r.tier}  laser={r.required_laser_file}  smelt→{r.ingot_identifier}')
        print(f'  locations={len(r.locations)}')
        for loc in r.locations[:3]:
            print(f'    {loc.distribution}: y={loc.y_start}..{loc.y_end} freq={loc.frequency} extent={loc.extent}')
