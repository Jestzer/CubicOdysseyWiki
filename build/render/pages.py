"""Renderers for the local wiki. Produces:
  - index.html
  - <category>.html (ores, ingots, tools, weapons, resources)
  - <category>/<slug>.html for every entry
  - assets/data.json (search manifest)
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).parent / 'templates'


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(['html', 'xml']),
        keep_trailing_newline=True,
    )


def _slug(identifier: str) -> str:
    return identifier.replace('.', '_').replace(' ', '_').lower()


def _icon_path(identifier: str, icons_dir: Path, root_assets: str = 'assets/icons/') -> Optional[str]:
    """Return relative-to-wiki-root icon path if a sliced icon exists."""
    fn = _slug(identifier) + '.png'
    if (icons_dir / fn).exists():
        return root_assets + fn
    return None


def _group_locations(locations: List[Any], dist_meta: dict) -> List[dict]:
    """Collapse multiple layer entries per distribution into one row per
    (distribution, role) with the union Y range and the maximum frequency.
    Keeps the output tight on each ore page. Layers with m_frequency == 0
    are skipped (the engine treats that as absent)."""
    by_dist = defaultdict(list)
    for loc in locations:
        if (loc.frequency or 0) == 0:
            continue
        by_dist[loc.distribution].append(loc)
    rows = []
    for dist, locs in by_dist.items():
        if dist in ('debug', 'default'):
            continue
        meta = dist_meta.get(dist, {})
        ystart = min(l.y_start for l in locs)
        yend = max(l.y_end for l in locs)
        max_freq = max(l.frequency for l in locs)
        extents = [l.extent for l in locs if l.extent]
        avg_ext = int(sum(extents) / len(extents)) if extents else None
        rows.append({
            'distribution': dist,
            'label': meta.get('label', dist),
            'short': meta.get('short', ''),
            'description': meta.get('description', ''),
            'y_start': ystart,
            'y_end': yend,
            'frequency': max_freq,
            'extent': avg_ext,
            'planets': meta.get('planets') or [],
        })
    rows.sort(key=lambda r: (-r['frequency'], r['label']))
    return rows


class WikiRenderer:
    def __init__(self, out_dir: Path, icons_dir: Path, dist_meta: dict, game_version: str):
        self.out = out_dir
        self.icons_dir = icons_dir
        self.dist_meta = dist_meta
        self.env = _make_env()
        self.build_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        self.game_version = game_version
        self.counts: Dict[str, int] = {}

    # ------------------------------------------------------------------

    def render(self,
               ore_records: list,
               ingot_records: list,
               tool_records: list,
               weapon_records: list,
               resource_records: list,
               gem_records: list = None,
               world_records: list = None):
        gem_records = gem_records or []
        world_records = world_records or []
        # Resolve icons + cross-links once
        ingot_lookup = {r['identifier']: r for r in ingot_records}
        ore_lookup = {r['identifier']: r for r in ore_records}

        # Attach icons to every record
        for rec_list, sub in (
            (ore_records, 'ores'), (gem_records, 'gems'),
            (ingot_records, 'ingots'),
            (tool_records, 'tools'), (weapon_records, 'weapons'),
            (resource_records, 'resources'),
        ):
            for r in rec_list:
                r['icon'] = _icon_path(r['identifier'], self.icons_dir)

        # Pre-compute ore locations grouping for templates
        for r in ore_records:
            locs = r.get('locations') or []
            class _L:  # cheap dataclass-y wrapper so _group_locations can use attrs
                pass
            loc_objs = []
            for l in locs:
                o = _L()
                for k, v in l.items():
                    setattr(o, k, v)
                loc_objs.append(o)
            r['locations_grouped'] = _group_locations(loc_objs, self.dist_meta)

        # Counts (guides added by render_guides; default to 7 here)
        self.counts = {
            'ores': len(ore_records),
            'gems': len(gem_records),
            'ingots': len(ingot_records),
            'tools': len(tool_records),
            'weapons': len(weapon_records),
            'resources': len(resource_records),
            'worlds': len(world_records),
            'guides': 7,
            'total': (len(ore_records) + len(gem_records) + len(ingot_records)
                       + len(tool_records) + len(weapon_records)
                       + len(resource_records) + len(world_records) + 7),
        }

        # Render index
        top_ores = sorted([r for r in ore_records if not r.get('is_glowing')],
                           key=lambda r: r['tier'])[:8]
        self._render_template(
            'index.html.j2',
            self.out / 'index.html',
            root='',
            category='home',
            title='Home',
            counts=self.counts,
            top_ores=top_ores,
        )

        # Render categories
        self._render_category('ores',
            ore_records,
            title='Ores',
            intro='Mineable ore blocks. Mining laser requirement and world distribution shown per entry.',
            extra_cols=[{'key': 'required_laser_file', 'label': 'Tool', 'mono': True}],
        )

        self._render_category('gems',
            gem_records,
            title='Gems',
            intro='Diamond, Ruby, Emerald, Sapphire (tier 5) and Glowing variants (tier 7). All four base gems share identical spawn tables — they always appear together in the same layer.',
            extra_cols=[{'key': 'required_laser_file', 'label': 'Tool', 'mono': True}],
        )

        # Attach ingot smelt_from references
        for r in ingot_records:
            if r.get('smelted_from_identifier'):
                src = ore_lookup.get(r['smelted_from_identifier'])
                if src:
                    r['smelted_from'] = {
                        'slug': src['slug'],
                        'display': src['display'],
                        'tier': src['tier'],
                    }
        self._render_category('ingots',
            ingot_records,
            title='Ingots',
            intro='Smelted metal/refined-resource outputs. Each links back to its source ore and smelting cost.',
            extra_cols=[],
        )

        self._render_category('tools',
            tool_records,
            title='Tools',
            intro='Mining lasers, ore extractors, backpacks, fishing rods, drones — the utility kit.',
            extra_cols=[],
        )
        self._render_category('weapons',
            weapon_records,
            title='Weapons',
            intro='Ranged and melee combat weapons. Mining lasers (utility) are listed under Tools. Each weapon shows whether it is craftable, looted, NPC-only, or unobtainable — derived from the game\'s recipes, randomsets, and character configs.',
            extra_cols=[{'key': 'obtain_label', 'label': 'Obtain', 'mono': False}],
        )
        self._render_category('resources',
            resource_records,
            title='Resources',
            intro='Raw materials, ammo, consumables, fuel cells, fragments, keys, and miscellaneous items.',
            extra_cols=[],
        )

        # Detail pages
        ingot_displays = {r['identifier']: r['display'] for r in ingot_records}
        for r in ore_records:
            self._render_template('ore.html.j2',
                self.out / 'ores' / (r['slug'] + '.html'),
                root='../', category='ores', title=r['display'],
                counts=self.counts, r=r, ingot_displays=ingot_displays)
        for r in gem_records:
            self._render_template('gem.html.j2',
                self.out / 'gems' / (r['slug'] + '.html'),
                root='../', category='gems', title=r['display'],
                counts=self.counts, r=r)
        for r in ingot_records:
            self._render_template('ingot.html.j2',
                self.out / 'ingots' / (r['slug'] + '.html'),
                root='../', category='ingots', title=r['display'],
                counts=self.counts, r=r)
        for r in tool_records:
            self._render_template('tool.html.j2',
                self.out / 'tools' / (r['slug'] + '.html'),
                root='../', category='tools', title=r['display'],
                counts=self.counts, r=r)
        for r in weapon_records:
            self._render_template('weapon.html.j2',
                self.out / 'weapons' / (r['slug'] + '.html'),
                root='../', category='weapons', title=r['display'],
                counts=self.counts, r=r)
        for r in resource_records:
            self._render_template('resource.html.j2',
                self.out / 'resources' / (r['slug'] + '.html'),
                root='../', category='resources', title=r['display'],
                counts=self.counts, r=r)

        # World types: overview + per-world detail
        if world_records:
            self._render_template('worlds_index.html.j2',
                self.out / 'worlds.html',
                root='', category='worlds', title='Worlds',
                counts=self.counts, worlds=world_records)
            for r in world_records:
                self._render_template('world.html.j2',
                    self.out / 'worlds' / (r['slug'] + '.html'),
                    root='../', category='worlds', title=r['display'],
                    counts=self.counts, r=r)

        # data.json search manifest
        manifest = []
        for cat, rec_list in (
            ('ores', ore_records), ('gems', gem_records),
            ('ingots', ingot_records),
            ('tools', tool_records), ('weapons', weapon_records),
            ('resources', resource_records),
        ):
            for r in rec_list:
                manifest.append({
                    'id': r['identifier'],
                    'name': r['display'],
                    'slug': r['slug'],
                    'category': cat,
                    'tier': r.get('tier', 0),
                    'icon': r.get('icon') or '',
                    'url': f"{cat}/{r['slug']}.html",
                })
        for r in world_records:
            manifest.append({
                'id': r['biomes_name'],
                'name': r['display'],
                'slug': r['slug'],
                'category': 'worlds',
                'tier': 0,
                'icon': '',
                'url': f"worlds/{r['slug']}.html",
            })
        # Guides also surface in global search
        for slug, title in (
            ('motherboards', 'Finding Motherboards'),
            ('leveling-mining', 'Leveling Mining'),
            ('leveling-trading', 'Leveling Trading'),
            ('item-damage', 'How damage affects items'),
            ('player-death', 'What happens when you die'),
            ('perks', 'Outpost perks'),
            ('gems', 'Gems and Gem Plates'),
        ):
            manifest.append({
                'id': f'guide.{slug}',
                'name': title,
                'slug': slug,
                'category': 'guides',
                'tier': 0,
                'icon': '',
                'url': f'guides/{slug}.html',
            })
        (self.out / 'assets' / 'data.json').write_text(
            json.dumps(manifest, indent=0, separators=(',', ':')),
            encoding='utf-8')

    def render_guides(self, *, motherboards_ctx: dict, mining_ctx: dict,
                       trading_ctx: dict, item_damage_ctx: dict,
                       player_death_ctx: dict, perks_ctx: dict,
                       gems_ctx: dict, summaries: dict):
        # Guides index
        self._render_template(
            'guides_index.html.j2',
            self.out / 'guides.html',
            root='', category='guides',
            title='Guides',
            counts=self.counts,
            guides=summaries,
        )
        # Detail pages
        self._render_template(
            'guide_motherboards.html.j2',
            self.out / 'guides' / 'motherboards.html',
            root='../', category='guides', title='Finding Motherboards',
            counts=self.counts,
            **motherboards_ctx,
        )
        self._render_template(
            'guide_mining.html.j2',
            self.out / 'guides' / 'leveling-mining.html',
            root='../', category='guides', title='Leveling Mining',
            counts=self.counts,
            **mining_ctx,
        )
        self._render_template(
            'guide_trading.html.j2',
            self.out / 'guides' / 'leveling-trading.html',
            root='../', category='guides', title='Leveling Trading',
            counts=self.counts,
            **trading_ctx,
        )
        self._render_template(
            'guide_item_damage.html.j2',
            self.out / 'guides' / 'item-damage.html',
            root='../', category='guides', title='How damage affects items',
            counts=self.counts,
            **item_damage_ctx,
        )
        self._render_template(
            'guide_player_death.html.j2',
            self.out / 'guides' / 'player-death.html',
            root='../', category='guides', title='What happens when you die',
            counts=self.counts,
            **player_death_ctx,
        )
        self._render_template(
            'guide_perks.html.j2',
            self.out / 'guides' / 'perks.html',
            root='../', category='guides', title='Outpost perks',
            counts=self.counts,
            **perks_ctx,
        )
        self._render_template(
            'guide_gems.html.j2',
            self.out / 'guides' / 'gems.html',
            root='../', category='guides', title='Gems and Gem Plates',
            counts=self.counts,
            **gems_ctx,
        )

    # ------------------------------------------------------------------

    def _render_category(self, slug: str, rows: list, *,
                          title: str, intro: str = '',
                          extra_cols: Optional[List[dict]] = None):
        tiers = sorted({r['tier'] for r in rows if isinstance(r.get('tier'), int)})
        self._render_template(
            'category.html.j2',
            self.out / f'{slug}.html',
            root='',
            category=slug,
            title=title,
            intro=intro,
            counts=self.counts,
            rows=sorted(rows, key=lambda r: (r['tier'], r['display'])),
            tiers=tiers,
            extra_cols=extra_cols or [],
        )

    def _render_template(self, template_name: str, out_path: Path, **ctx):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.setdefault('build_time', self.build_time)
        ctx.setdefault('game_version', self.game_version)
        ctx.setdefault('counts', self.counts)
        html = self.env.get_template(template_name).render(**ctx)
        out_path.write_text(html, encoding='utf-8')
