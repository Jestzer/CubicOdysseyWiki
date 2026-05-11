"""Enemy records — pirate / zombie characters that drop loot.

Each entry combines data/configs/characters/*.cfg with the randomset
named in its dropLoot field. We classify by `defaultTeam`:

- PIRATES: human pirates, multiple tiers
- ZOMBIES: corruption-zone undead, drop dark / matter resources
- VILLAGERS soldiers: technically allied but visible as combatants
"""

from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug


HOSTILE_TEAMS = {'PIRATES', 'ZOMBIES'}


def _link_item(identifier: str, cat: Catalog) -> Optional[str]:
    item = cat.items.get(identifier)
    if not item:
        return None
    t = item.get('type', '')
    slug = _slug(identifier)
    if t == 'RAW_ORE':
        return f'ores/{slug}.html'
    if identifier in {'res.diamond','res.ruby','res.emerald','res.sapphire',
                       'res.glowing.diamond','res.glowing.ruby',
                       'res.glowing.emerald','res.glowing.sapphire'}:
        return f'gems/{slug}.html'
    if t == 'PROCESSED_ORE' or identifier.endswith('.ingot'):
        return f'ingots/{slug}.html'
    if t == 'UTILS':
        return f'tools/{slug}.html'
    if t in ('WEAPON_RANGED', 'WEAPON_MELEE'):
        return f'weapons/{slug}.html'
    if t in {'RESOURCE','AMMO','CONSUMABLE','CREATURE_RESOURCE',
              'DARK_RESOURCE','KEY','MOD','PART','WAREZ'}:
        return f'resources/{slug}.html'
    return None


def build_enemy_records(cat: Catalog) -> List[dict]:
    records: List[dict] = []
    for fname, char in cat.characters.items():
        team = char.get('defaultTeam')
        if team not in HOSTILE_TEAMS:
            continue
        drop_name = char.get('dropLoot') or ''
        drops = []
        if drop_name and drop_name in cat.randomsets:
            rs = cat.randomsets[drop_name]
            for entry in (rs.get('m_items') or []):
                if not isinstance(entry, dict):
                    continue
                iid = entry.get('m_item', '')
                item = cat.items.get(iid)
                display = _humanize(item.get('title_string') or iid) if item else iid
                drops.append({
                    'identifier': iid,
                    'display': display,
                    'chance': entry.get('m_chance'),
                    'min_count': entry.get('m_minCount'),
                    'max_count': entry.get('m_maxCount'),
                    'url': _link_item(iid, cat),
                })
            drops.sort(key=lambda d: -(d['chance'] or 0))

        weapon_id = char.get('weapon')
        weapon_link = None
        weapon_display = None
        if weapon_id:
            witem = cat.items.get(weapon_id)
            if witem:
                weapon_display = _humanize(witem.get('title_string') or weapon_id)
                weapon_link = _link_item(weapon_id, cat)
            else:
                weapon_display = weapon_id

        records.append({
            'slug': _slug(fname),
            'identifier': fname,
            'display': _humanize_enemy_name(fname),
            'team': team,
            'life': char.get('life'),
            'shield': char.get('shieldCapacity'),
            'walk_speed': char.get('walkSpeed'),
            'sprint_mult': char.get('sprintMultiplier'),
            'jump_height': char.get('jumpHeight'),
            'scale': char.get('scale'),
            'weapon_id': weapon_id,
            'weapon_display': weapon_display,
            'weapon_link': weapon_link,
            'ai_template': char.get('ai_template'),
            'npc_type': char.get('npcType'),
            'weapon_type': char.get('weaponType'),
            'skin': char.get('skin'),
            'drop_table_name': drop_name,
            'drops': drops,
            'tier': _enemy_tier(fname, char),
        })

    records.sort(key=lambda r: (r['team'], r['life'] or 0, r['display']))
    return records


def _humanize_enemy_name(filename: str) -> str:
    parts = filename.replace('n_pirate_', 'newbie_pirate_') \
                     .replace('s_pirate_', 'special_pirate_') \
                     .split('_')
    return ' '.join(p.capitalize() for p in parts)


def _enemy_tier(fname: str, char: dict) -> int:
    """Rough difficulty tier from HP and weapon naming. Lets the wiki
    sort 'beginner pirate' before 'elite pirate' even when life values are
    similar."""
    life = char.get('life') or 50
    if 'elite' in fname.lower():
        return 4
    if life < 60:
        return 1
    if life < 90:
        return 2
    if life < 120:
        return 3
    return 4
