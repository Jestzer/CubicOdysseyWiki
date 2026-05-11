"""Build the data context for each Guides page.

Each `build_*_context()` returns a dict ready for Jinja2 rendering.
"""

from pathlib import Path
from typing import Dict, List, Optional

from extract.catalog import Catalog
from extract.ores import _humanize, _slug


GUIDE_SUMMARIES = {
    'motherboards': {
        'subtitle': 'Tier-3 part — not craftable',
        'summary': 'Motherboards gate every tier-4 personal upgrade and MK3 ship component. Locate them, hoard them, spend them wisely.',
    },
    'mining': {
        'subtitle': 'Skill #1 of the 9 — easiest to grind',
        'summary': 'How Mining XP works, which mining laser to chase, which ores reward best per tier, and where to find them.',
    },
    'trading': {
        'subtitle': 'Stack discounts and flip what merchants want',
        'summary': 'Where Trading XP comes from, the Trade Discount perk, and which items have actual flip value based on base_price × base_demand.',
    },
    'item-damage': {
        'subtitle': 'Durability, repair benches, recycle',
        'summary': '389 items in the game track durability. How damage works, what happens at 0, and which station to repair at.',
    },
    'player-death': {
        'subtitle': 'Tombstones, doctors, what you lose',
        'summary': 'Player HP is only 60. What spawns when you die, how to recover your stuff, and how the doctor NPC fits in.',
    },
}


def _link_for(identifier: str, cat: Catalog) -> Optional[str]:
    """Return the wiki URL (relative to root) for an item identifier, if it
    falls into one of the categories we render detail pages for."""
    item = cat.items.get(identifier)
    if not item:
        return None
    t = item.get('type', '')
    slug = _slug(identifier)
    if t == 'RAW_ORE':
        return f'ores/{slug}.html'
    if t == 'PROCESSED_ORE' or identifier.endswith('.ingot'):
        return f'ingots/{slug}.html'
    if t == 'UTILS':
        return f'tools/{slug}.html'
    if t in ('WEAPON_RANGED', 'WEAPON_MELEE'):
        return f'weapons/{slug}.html'
    if t in ('RESOURCE', 'AMMO', 'CONSUMABLE', 'CREATURE_RESOURCE',
              'DARK_RESOURCE', 'KEY', 'MOD', 'PART', 'WAREZ'):
        return f'resources/{slug}.html'
    return None


def motherboard_context(cat: Catalog, icons_dir: Path) -> dict:
    mb = cat.items.get('res.motherboard') or {}
    icon = f'assets/icons/res_motherboard.png' if (
        icons_dir / 'res_motherboard.png').exists() else None
    motherboard = {
        'identifier': 'res.motherboard',
        'display': 'Motherboard',
        'icon': icon,
        'tier': mb.get('tier'),
        'stack_size': mb.get('stack_size'),
        'base_price': mb.get('base_price'),
        'recycle_value': mb.get('recycle_value'),
        'base_demand': mb.get('base_demand'),
        'inv_frame': mb.get('inv_frame'),
    }

    # Recipes using motherboards
    using = cat.recipes_using('res.motherboard')
    rows = []
    for r in using:
        qty = 0
        for inp in r.get('inputItems', []):
            if isinstance(inp, dict) and inp.get('item') == 'res.motherboard':
                qty = inp.get('quantity', 0)
                break
        crafted = r.get('craftedObject', '')
        crafted_display = _humanize(cat.items.get(crafted, {}).get('title_string') or crafted)
        rows.append({
            'crafted_object': crafted,
            'crafted_display': crafted_display,
            'crafted_link': _link_for(crafted, cat),
            'motherboard_qty': qty,
            'needed_skill_type': r.get('neededSkillType', '—'),
            'needed_skill_level': r.get('neededSkillLevel', '—'),
            'category': r.get('category', ''),
        })
    rows.sort(key=lambda x: (-x['motherboard_qty'], x['crafted_object']))

    bunker_rooms = []
    if cat.game_root:
        rs_dir = cat.game_root / 'data' / 'configs' / 'randomsets'
        if rs_dir.is_dir():
            for p in sorted(rs_dir.glob('bunker_*.cfg')):
                bunker_rooms.append(p.stem)

    return {
        'motherboard': motherboard,
        'recipes_using': rows,
        'recipes_total': len(cat.crafting_recipes),
        'bunker_rooms': bunker_rooms,
    }


def mining_context(cat: Catalog, ore_records: List[dict],
                    tool_records: List[dict], icons_dir: Path) -> dict:
    # Mining lasers, ordered
    lasers = []
    for t in tool_records:
        if 'mining_laser' in t['identifier']:
            stats = t.get('weapon_stats') or {}
            vt = stats.get('voxel_tier', 0) or 0
            dmg = stats.get('voxel_damage') or 0
            rpm = stats.get('fireRateRPM') or 0
            # DPS hint = damage * (rpm/60)
            dps_hint = f"{(dmg * rpm / 60):.1f}" if (dmg and rpm) else "—"
            mines_up_to = f"voxel tier {vt} (T{vt} ores)"
            lasers.append({
                'identifier': t['identifier'],
                'slug': t['slug'],
                'display': t['display'],
                'icon': t.get('icon'),
                'tier': t['tier'],
                'voxel_tier': vt,
                'mines_up_to': mines_up_to,
                'dps_hint': dps_hint,
            })
    lasers.sort(key=lambda l: l['identifier'])

    # Group ores by tier
    ores_by_tier: Dict[int, list] = {}
    glowing_count = 0
    for o in ore_records:
        if o.get('is_glowing'):
            glowing_count += 1
        ores_by_tier.setdefault(o['tier'], []).append({
            'display': o['display'],
            'slug': o['slug'],
        })

    return {
        'lasers': lasers,
        'ores_by_tier': ores_by_tier,
        'glowing_count': glowing_count,
    }


def trading_context(cat: Catalog, ore_records: List[dict],
                     ingot_records: List[dict], tool_records: List[dict],
                     weapon_records: List[dict], resource_records: List[dict]
                     ) -> dict:
    # Outpost perks
    perks_dir = cat.game_root / 'data' / 'configs' / 'outpostperks' if cat.game_root else None
    from parsers.cfg import parse_file
    perk_data = {}
    if perks_dir and perks_dir.is_dir():
        for p in perks_dir.glob('*.cfg'):
            d = parse_file(p)
            if isinstance(d, dict):
                perk_data[p.stem] = d
    trade_perk = perk_data.get('TRADE_DISCOUNT_1', {})
    hp_perk = perk_data.get('HP_REGEN_1', {})
    proc_perk = perk_data.get('PROCESSING_SPEED_1', {})

    def perk_view(d):
        return {'id': d.get('id', '—'), 'value': d.get('m_value', 0)}

    # Collect every catalog item with both fields, build flippable / vendor lists
    candidates = []
    for ident, it in cat.items.items():
        bp = it.get('base_price')
        bd = it.get('base_demand')
        if bp is None or bd is None:
            continue
        slug = _slug(ident)
        candidates.append({
            'identifier': ident,
            'display': _humanize(it.get('title_string') or ident),
            'base_price': bp,
            'base_demand': bd,
            'type': it.get('type', ''),
            'icon': f'assets/icons/{slug}.png',
            'url': _link_for(ident, cat) or '#',
            'score': bp * bd,
        })

    high_demand = sorted(
        [c for c in candidates if c['base_demand'] > 0 and c['url'] != '#'],
        key=lambda c: c['score'], reverse=True,
    )
    vendor_stock = sorted(
        [c for c in candidates if c['base_demand'] < 0 and c['url'] != '#'],
        key=lambda c: c['base_demand'],
    )

    return {
        'trade_perk': perk_view(trade_perk),
        'hp_perk': perk_view(hp_perk),
        'proc_perk': perk_view(proc_perk),
        'high_demand': high_demand,
        'vendor_stock': vendor_stock,
    }


def item_damage_context(cat: Catalog, icons_dir: Path) -> dict:
    """Survey items with durability fields + describe the repair stations."""
    # Distribution by durability value
    counts: Dict[int, int] = {}
    types_with_dur: Dict[str, int] = {}
    examples: List[dict] = []
    for ident, it in cat.items.items():
        dur = it.get('durability')
        if dur is None:
            continue
        counts[dur] = counts.get(dur, 0) + 1
        t = it.get('type', '')
        types_with_dur[t] = types_with_dur.get(t, 0) + 1
        examples.append({
            'identifier': ident,
            'display': _humanize(it.get('title_string') or ident),
            'tier': it.get('tier', 1),
            'type': t,
            'durability': dur,
            'recycle_value': it.get('recycle_value'),
            'base_price': it.get('base_price'),
            'icon': f'assets/icons/{_slug(ident)}.png',
            'url': _link_for(ident, cat) or '#',
        })

    by_durability = sorted(counts.items(), key=lambda kv: -kv[1])
    types_sorted = sorted(types_with_dur.items(), key=lambda kv: -kv[1])

    # A small curated example list — highest and lowest durability items
    examples_sorted = sorted(examples, key=lambda e: (-e['durability'], e['tier'], e['display']))
    high_dur_samples = examples_sorted[:6]
    low_dur_samples = sorted(examples, key=lambda e: (e['durability'], e['tier'], e['display']))[:6]

    # Repair bench items
    rb = cat.items.get('dpl.repair_bench.1') or {}
    rbq = cat.items.get('dpl.repair_bench.qubits') or {}
    def view(it, identifier):
        return {
            'identifier': identifier,
            'display': _humanize(it.get('title_string') or identifier),
            'tier': it.get('tier'),
            'type': it.get('type', ''),
            'icon': f'assets/icons/{_slug(identifier)}.png' if (icons_dir / (_slug(identifier) + '.png')).exists() else None,
        }

    # Look up the REPAIRING_BENCH recipe (Crafting 1)
    repair_recipe = None
    for r in cat.crafting_recipes:
        if r.get('_file') == 'REPAIRING_BENCH':
            repair_recipe = r
            break
    repair_inputs = []
    if repair_recipe:
        for inp in (repair_recipe.get('inputItems') or []):
            if not isinstance(inp, dict):
                continue
            iid = inp.get('item', '')
            repair_inputs.append({
                'item': iid,
                'display': _humanize(cat.items.get(iid, {}).get('title_string') or iid),
                'qty': inp.get('quantity'),
                'url': _link_for(iid, cat) or '#',
            })

    return {
        'total_items_with_durability': len(examples),
        'by_durability': by_durability[:8],   # top 8 most-common durability values
        'types_sorted': types_sorted[:12],
        'high_dur_samples': high_dur_samples,
        'low_dur_samples': low_dur_samples,
        'repair_bench': view(rb, 'dpl.repair_bench.1'),
        'repair_bench_qubits': view(rbq, 'dpl.repair_bench.qubits'),
        'repair_recipe_skill': repair_recipe.get('neededSkillLevel') if repair_recipe else None,
        'repair_inputs': repair_inputs,
    }


def player_death_context(cat: Catalog, icons_dir: Path) -> dict:
    """Pull player HP, death-chest data, doctor data, mob HP comparison."""
    # Read player.cfg
    player_path = cat.game_root / 'data' / 'configs' / 'characters' / 'player.cfg'
    from parsers.cfg import parse_file
    player_data = parse_file(player_path) or {}

    # All other characters (life + team)
    chars_dir = cat.game_root / 'data' / 'configs' / 'characters'
    mobs = []
    for p in sorted(chars_dir.glob('*.cfg')):
        d = parse_file(p)
        if not isinstance(d, dict):
            continue
        life = d.get('life')
        team = d.get('team')
        if life is None:
            continue
        mobs.append({
            'name': p.stem,
            'life': life,
            'team': d.get('defaultTeam', team or ''),
            'weapon': d.get('weapon'),
            'shield': d.get('shieldCapacity'),
            'is_player': p.stem == 'player',
        })
    # Sort by life ascending, then alpha. Keep player at the top of the table.
    mobs.sort(key=lambda m: (m['life'], m['name']))

    # Death chest
    dc = cat.items.get('dpl.deathchest') or {}
    death_chest = {
        'identifier': 'dpl.deathchest',
        'display': _humanize(dc.get('title_string') or 'STR_DEATH_CHEST'),
        'tier': dc.get('tier'),
        'invincible': dc.get('invincible'),
        'world_model': dc.get('world_model'),
        'icon': f'assets/icons/dpl_deathchest.png' if (icons_dir / 'dpl_deathchest.png').exists() else None,
    }

    # Doctor (NPC)
    doc_path = cat.game_root / 'data' / 'configs' / 'characters' / 'npc_doctor.cfg'
    doc_data = parse_file(doc_path) or {}
    doctor = {
        'life': doc_data.get('life'),
        'shield': doc_data.get('shieldCapacity'),
        'interaction': doc_data.get('interaction'),
        'weapon': doc_data.get('weapon'),
    }

    # Grouped HP buckets
    buckets = {'PLAYER': [], 'VILLAGERS': [], 'PIRATES': [], 'ZOMBIES': []}
    for m in mobs:
        team = m['team'] or ''
        if team in buckets:
            buckets[team].append(m)

    return {
        'player_life': player_data.get('life'),
        'player_walk': player_data.get('walkSpeed'),
        'player_sprint_mul': player_data.get('sprintMultiplier'),
        'player_jump': player_data.get('jumpHeight'),
        'death_chest': death_chest,
        'doctor': doctor,
        'mobs': mobs,
        'buckets': buckets,
    }


def all_guide_summaries() -> dict:
    return GUIDE_SUMMARIES
