"""Ship records.

The game ships ~70 entries in data/configs/ships/ and pairs them with
SHIP-typed items in data/configs/items/. Each ship has a class (L0–L4)
controlling which component MKs fit it; components are class-locked.

Each ship is also assigned a sub-class **role** (Scout, Interceptor,
Fighter, Trader, …). The game data does not expose an explicit role
field, so the role is derived from the ship's blueprint composition —
component family (karve vs corvette = sub-hull size), per-slot MK level
(cargo vs combat emphasis), and named-chassis variants (mark unique
"ace" ships).
"""

import re
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


# All role labels in display order. Used by the Ships index to seed the
# filter pill set so a role never goes missing when 0 ships happen to
# match.
ROLE_ORDER = [
    'Drone',
    'Scout',
    'Light Fighter', 'Fighter', 'Heavy Fighter', 'Ace Fighter',
    'Interceptor', 'Trader',
    'Cruiser', 'Stealth Cruiser', 'Heavy Cruiser', 'Battlecruiser',
    'Elite Cruiser', 'Transport',
    'Battleship', 'Heavy Battleship', 'Dreadnought',
    'Light Carrier', 'Carrier', 'Heavy Carrier', 'Mothership',
    'Unclassified',
]


def _parse_slot_components(blueprint: dict) -> Dict[str, str]:
    """Return {slot_type: component_id} for a parsed blueprint."""
    out: Dict[str, str] = {}
    slots = blueprint.get('m_slots') or []
    if not isinstance(slots, list):
        return out
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        t = slot.get('m_type')
        c = slot.get('m_presentComponent')
        if t:
            out[t] = c or ''
    return out


def _mk_level(comp_id: str) -> int:
    if not comp_id:
        return 0
    m = re.search(r'mk(\d+)', comp_id)
    return int(m.group(1)) if m else 0


def _family(comp_id: str) -> str:
    """Hull family hinted by the component id.

    Most components encode the family in the second segment, e.g.
    ``comp.corvette.engine.space.mk1`` → ``corvette``. Lasers reverse
    the convention: ``comp.laser.karve.mk1`` → ``karve``.
    """
    if not comp_id:
        return ''
    parts = comp_id.split('.')
    if len(parts) < 2:
        return ''
    if comp_id.startswith('comp.laser.') and len(parts) >= 3:
        return parts[2]
    return parts[1]


def _has_named_chassis(comp_id: str) -> bool:
    """Detect a named chassis variant like ``comp.corvette.chassis.excalibur.mk5``.

    A plain chassis has 4 segments (``comp.<family>.chassis.mk<N>``).
    A named one has 5 (``comp.<family>.chassis.<name>.mk<N>``).
    """
    if not comp_id:
        return False
    parts = comp_id.split('.')
    return (len(parts) >= 5
            and parts[0] == 'comp'
            and parts[2] == 'chassis'
            and not parts[3].startswith('mk'))


def _derive_role(klass: str, tier: int, blueprint: Optional[dict]) -> str:
    """Pick a role label for a ship.

    Drives off the blueprint's component composition. The rules are
    documented at module top — briefly: karve family → Scout, cargo MK
    above the combat-slot average → Trader/Transport, named chassis →
    Ace/Elite, plus tier-aware defaults per hull class.
    """
    if klass == 'L0_DRONE':
        return 'Drone'
    if not blueprint:
        return _class_default_role(klass, tier)

    comps = _parse_slot_components(blueprint)
    engine_mk = _mk_level(comps.get('ENGINE', ''))
    laser_mk = _mk_level(comps.get('LASER', ''))
    cargo_mk = _mk_level(comps.get('CARGO', ''))
    shield_mk = _mk_level(comps.get('SHIELD', ''))
    chassis_mk = _mk_level(comps.get('CHASSIS', ''))
    fam = _family(comps.get('ENGINE') or comps.get('LASER')
                   or comps.get('CHASSIS') or '')
    named = _has_named_chassis(comps.get('CHASSIS', ''))

    combat_mks = [m for m in (laser_mk, shield_mk, chassis_mk) if m]
    combat_avg = sum(combat_mks) / len(combat_mks) if combat_mks else 0.0
    cargo_emphasis = cargo_mk and combat_avg and cargo_mk > combat_avg + 0.4
    speed_emphasis = (engine_mk and combat_avg
                      and engine_mk > combat_avg + 0.4)

    # Sub-hull family within the corvette class.
    if klass == 'L1_CORVETTE' and fam == 'karve':
        return 'Scout'

    if klass == 'L1_CORVETTE':
        if cargo_emphasis:
            return 'Trader'
        if named:
            return 'Ace Fighter'
        if speed_emphasis:
            return 'Interceptor'
        if tier <= 2:
            return 'Light Fighter'
        if tier == 5:
            return 'Heavy Fighter'
        return 'Fighter'

    if klass == 'L2_FRIGATE':
        if cargo_emphasis:
            return 'Transport'
        if named:
            return 'Elite Cruiser'
        if tier <= 1:
            return 'Cruiser'
        if tier == 5:
            return 'Battlecruiser'
        return 'Heavy Cruiser'

    if klass == 'L3_DREADNOUGHT':
        if cargo_emphasis:
            return 'Transport'
        if named:
            return 'Heavy Battleship'
        if tier <= 1:
            return 'Cruiser'
        if tier == 5:
            return 'Dreadnought'
        return 'Battleship'

    if klass == 'L4_GALLEON':
        if named:
            return 'Heavy Carrier'
        if tier <= 1:
            return 'Light Carrier'
        if tier == 5:
            return 'Mothership'
        if tier >= 4:
            return 'Heavy Carrier'
        return 'Carrier'

    return _class_default_role(klass, tier)


def _class_default_role(klass: str, tier: int) -> str:
    """Fallback when a blueprint is missing — defer to class + tier."""
    if klass == 'L0_DRONE':
        return 'Drone'
    if klass == 'L1_CORVETTE':
        return 'Fighter'
    if klass == 'L2_FRIGATE':
        return 'Cruiser'
    if klass == 'L3_DREADNOUGHT':
        return 'Battleship' if tier and tier >= 3 else 'Cruiser'
    if klass == 'L4_GALLEON':
        return 'Carrier'
    return 'Unclassified'


def _resolve_blueprint(cat: Catalog, blueprint_name: Optional[str]) -> Optional[dict]:
    """Match the ship cfg's blueprint reference to a parsed blueprint
    in the catalog. Names may include the ``Blueprint_`` prefix or be
    short variants like ``corvette_mk1`` used by pirate ships."""
    if not blueprint_name:
        return None
    candidates = [blueprint_name]
    if not blueprint_name.startswith('Blueprint_'):
        candidates.append(f'Blueprint_{blueprint_name}')
    for c in candidates:
        bp = cat.blueprints.get(c)
        if bp:
            return bp
    # Case-insensitive last resort
    lower = blueprint_name.lower()
    for name, bp in cat.blueprints.items():
        if name.lower() == lower:
            return bp
    return None


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
        records.append(_record_from_item(cat, ident, item, config_stem, config))

    # Also surface configs that don't have a SHIP item (e.g. enemy variants)
    for stem, config in ship_configs.items():
        if stem in used_configs:
            continue
        records.append(_record_from_config(cat, stem, config))

    records.sort(key=lambda r: (r['class_order'], r['faction'], r['display']))
    return records


def _record_from_item(cat: Catalog, ident: str, item: dict, config_stem: Optional[str],
                       config: Optional[dict]) -> dict:
    config = config or {}
    klass = config.get('class', '')
    pilot = _pilot_kind(item, config)
    blueprint = _resolve_blueprint(cat, config.get('blueprint'))
    role = _derive_role(klass, item.get('tier') or 1, blueprint)
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
        'role': role,
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


def _record_from_config(cat: Catalog, stem: str, config: dict) -> dict:
    klass = config.get('class', '')
    pilot = _pilot_kind({}, config)
    blueprint = _resolve_blueprint(cat, config.get('blueprint'))
    role = _derive_role(klass, 1, blueprint)
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
        'role': role,
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
