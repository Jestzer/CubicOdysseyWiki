"""Ship records.

The game ships ~70 entries in data/configs/ships/ and pairs them with
SHIP-typed items in data/configs/items/. Each ship has a class (L0–L4)
controlling which component MKs fit it; components are class-locked.
"""

from pathlib import Path
from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug
from parsers.cfg import parse_file


CLASS_LABELS = {
    'L0_DRONE': 'Drone',
    'L1_CORVETTE': 'Corvette',
    'L2_FRIGATE': 'Frigate',
    'L3_DREADNOUGHT': 'Dreadnought',
    'L4_GALLEON': 'Galleon',
}


def build_ship_records(cat: Catalog) -> List[dict]:
    # Load every config in data/configs/ships/
    ship_configs: Dict[str, dict] = {}
    if cat.game_root:
        ships_dir = cat.game_root / 'data' / 'configs' / 'ships'
        if ships_dir.is_dir():
            for p in sorted(ships_dir.glob('*.cfg')):
                d = parse_file(p)
                if isinstance(d, dict):
                    ship_configs[p.stem] = d

    # Build the union: every SHIP-typed item, plus any ship config that has
    # no matching item (rare but possible).
    records: List[dict] = []
    used_configs = set()
    for ident, item in cat.items.items():
        if item.get('type') != 'SHIP':
            continue
        # Try to locate the matching ship config by item file stem
        config_stem = None
        config = None
        for stem, parsed in cat.items_by_file.items():
            if parsed.get('identifier') == ident:
                if stem in ship_configs:
                    config_stem = stem
                    config = ship_configs[stem]
                    used_configs.add(stem)
                break
        records.append(_record_from_item(ident, item, config_stem, config))

    # Also surface configs that don't have a SHIP item (e.g. enemy variants)
    for stem, config in ship_configs.items():
        if stem in used_configs:
            continue
        records.append(_record_from_config(stem, config))

    records.sort(key=lambda r: (r['class_order'], r['faction'], r['display']))
    return records


def _record_from_item(ident: str, item: dict, config_stem: Optional[str],
                       config: Optional[dict]) -> dict:
    config = config or {}
    klass = config.get('class', '')
    pilot = _pilot_kind(item, config)
    return {
        'identifier': ident,
        'slug': _slug(ident),
        'display': _humanize(item.get('title_string') or ident),
        'tier': item.get('tier', 1),
        'base_price': item.get('base_price'),
        'stack_size': item.get('stack_size'),
        'inv_frame': item.get('inv_frame'),
        'description_string': item.get('description_string'),
        'class_raw': klass,
        'class_label': CLASS_LABELS.get(klass, klass or 'Unknown'),
        'class_order': _class_order(klass),
        'faction': config.get('faction', 'GENERIC'),
        'category': config.get('category', 'SPACESHIP'),
        'blueprint': config.get('blueprint'),
        'drop_loot': config.get('drop_loot'),
        'ai_damage_scale': config.get('aiDamageScale'),
        'ai_speed_scale': config.get('aiSpeedScale'),
        'ai_turn_rate_scale': config.get('aiTurnRateScale'),
        'config_stem': config_stem,
        'pilot': pilot,
        'player_obtainable': pilot == 'player',
        'type': 'SHIP',
    }


def _record_from_config(stem: str, config: dict) -> dict:
    klass = config.get('class', '')
    pilot = _pilot_kind({}, config)
    return {
        'identifier': f'cfg.{stem.lower()}',
        'slug': _slug(stem),
        'display': _humanize(stem),
        'tier': None,
        'base_price': None,
        'stack_size': None,
        'inv_frame': None,
        'description_string': None,
        'class_raw': klass,
        'class_label': CLASS_LABELS.get(klass, klass or 'Unknown'),
        'class_order': _class_order(klass),
        'faction': config.get('faction', 'GENERIC'),
        'category': config.get('category', 'SPACESHIP'),
        'blueprint': config.get('blueprint'),
        'drop_loot': config.get('drop_loot'),
        'ai_damage_scale': config.get('aiDamageScale'),
        'ai_speed_scale': config.get('aiSpeedScale'),
        'ai_turn_rate_scale': config.get('aiTurnRateScale'),
        'config_stem': stem,
        'pilot': pilot,
        'player_obtainable': pilot == 'player',
        'type': 'SHIP_CONFIG',
    }


def _class_order(klass: str) -> int:
    order = ['L0_DRONE', 'L1_CORVETTE', 'L2_FRIGATE', 'L3_DREADNOUGHT', 'L4_GALLEON']
    return order.index(klass) if klass in order else 99


def _pilot_kind(item: dict, config: dict) -> str:
    """Classify who pilots this ship: 'player', 'pirate', 'police', or 'npc'.

    The strongest signal is the asset path — ships meant for the player live
    under data/models/.../player[_itch]/. Pirate/police variants live in their
    own folders and never have base_price set. Anything left over (e.g.
    SHIP_PLANET_PURIFIER_MOBILE, a quest-instance ship) falls into 'npc'.
    """
    faction = config.get('faction', '')
    binvox = (config.get('binvoxFile') or '').lower()
    world_model = (item.get('world_model') or '').lower()
    if '/player' in world_model or '/player' in binvox:
        return 'player'
    if faction == 'POLICE':
        return 'police'
    if faction == 'PIRATES':
        return 'pirate'
    return 'npc'


def build_speeder_records(cat: Catalog) -> List[dict]:
    records: List[dict] = []
    for ident, item in cat.items.items():
        if item.get('type') != 'SPEEDER':
            continue
        # camo_color sometimes reveals the speeder's signature shade
        color = item.get('camo_color')
        records.append({
            'identifier': ident,
            'slug': _slug(ident),
            'display': _humanize(item.get('title_string') or ident),
            'tier': item.get('tier', 1),
            'base_price': item.get('base_price'),
            'stack_size': item.get('stack_size'),
            'inv_frame': item.get('inv_frame'),
            'description_string': item.get('description_string'),
            'world_model': item.get('world_model'),
            'camo_color': color,
            'type': 'SPEEDER',
        })
    records.sort(key=lambda r: (r['tier'], r['display']))
    return records
