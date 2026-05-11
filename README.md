# Cubic Odyssey — local wiki

A static, self-hostable wiki for the game **Cubic Odyssey**, regenerated
directly from the game's `data/configs/` and `data/sprites/` on every build.

The v1 focus is **ores**: which tier they are, which mining laser is
required, which world types host them, what they smelt into, and how much
fuel/time it takes. Adjacent categories (ingots, tools, weapons, resources)
are also indexed.

There's also a **Guides** section covering:
- Finding **Motherboards** (a tier-3 part that gates every tier-4 upgrade
  and MK3 ship component but has no crafting recipe).
- Leveling **Mining** (which laser, which ore tier, which planet type).
- Leveling **Trading** (which items have positive demand vs vendor-supplied,
  and how the Trade Discount outpost perk stacks).

## Open the wiki

If the wiki has already been built:

```bash
xdg-open index.html         # Linux
open index.html             # macOS
```

Firefox handles the index's JSON-driven search via `file://` directly.
Chrome blocks `file://` JSON fetches by default — the index gracefully
falls back to category cards, or you can serve the directory:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000/
```

## (Re)build the wiki

The build script reads game data live and emits all HTML + icons.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r build/requirements.txt
python3 build/build.py
```

Outputs:

```
index.html              landing + global search
ores.html               sortable, filterable category overview
ores/<slug>.html        per-ore detail pages
ingots.html, ingots/    smelted-ore details
tools.html, tools/      mining lasers + utility items
weapons.html, weapons/  combat weapons
resources.html, resources/   raw materials, ammo, consumables, mods, ...
assets/icons/*.png      one per item (sliced from items01.png + items_dpl.png)
assets/data.json        search manifest (~500 entries)
data/catalog.json       full intermediate, for debugging
```

The build auto-detects the standard Linux/Proton install at
`/run/media/james/SSD/Program Files (x86)/Steam/steamapps/common/Cubic Odyssey/`.
Use `--game-path /custom/path` to point elsewhere.

## How the data is sourced

| Wiki field | Game source |
|---|---|
| Ore tier, hardness, drop, color | `data/configs/voxels/*.cfg` (`m_tier`, `m_mineUnit`, `m_dropItem`, `m_color`) |
| Item names + stats | `data/configs/items/*.cfg` |
| Mining laser tiers | `data/configs/rangedweapons/MINING_LASER_*.cfg` (`voxel_tier`) |
| Smelting recipes | `data/configs/furnace/*.cfg` |
| Where ores spawn | `data/configs/voxeldistributions/*.cfg` |
| Biome → distribution | `data/configs/worldbiomes/*.cfg` (`oreDistributionFile`) |
| Planet → biome group | `build/world_to_distribution.json` (hand-authored; see Limitations) |
| Item icons | `data/sprites/items01.bspr` + `.png`, `items_dpl.bspr` + `.png` |
| Display names | derived from `title_string` token (`STR_IRON_ORE` → "Iron Ore") |
| Crafting recipes | `data/configs/recipes/*.cfg` — `inputItems` × quantity, `neededSkillType`/`neededSkillLevel`, `craftedObject` |
| Skill list | `data/configs/achievements/max_level_*.cfg` — 9 skills + overall player level |
| Outpost perks | `data/configs/outpostperks/*.cfg` — only 3 exist (HP Regen, Processing Speed, Trade Discount) |
| Trade flip data | each item's `base_price` × `base_demand` from `data/configs/items/*.cfg` (positive demand = merchant-wanted; negative = vendor-supplied) |

The BSPR sprite-atlas parser and the `.cfg` parser are written in pure
Python (no .NET dependency); they're informed by the sibling project
`../CubicOdysseyVault`, which had already reverse-engineered both formats.

## Known limitations

- **Localization not decoded**. `data/localization/strings_*.str` files are
  in an obfuscated binary format that the Vault project has not yet cracked.
  Display names are humanized directly from the `STR_*` token, so a small
  fraction read awkwardly. Real localization can be wired in later.
- **Planet → distribution join is best-effort**. The game's `WorldCfg` only
  declares `m_biome0..7` as generic terrain types (`desert`, `mountains`,
  `random`, …) — there's no explicit link to a specific voxel-distribution
  file. `build/world_to_distribution.json` maps each distribution to a
  user-friendly *world type* (Earth-like, Scorched, Crystalline, …) plus a
  best-effort planet list where the biome set hard-codes one. Most planets
  pick biomes procedurally and will read as "(procedural — biome
  dependent)".
- **Atlas selection** picks `items01` first and falls back to `items_dpl`
  for deployables. A handful of items may show the wrong icon; correctable
  by extending the heuristic.
- **Out-of-v1-scope item types** (skipped or dumped under Resources):
  ships, ship components, speeders, habitats, armor / gear, drone gear,
  slopes, stairs, building parts. They're present in `data/catalog.json`
  for future passes.
- **Frequency / vein size** values on ore pages are the raw `m_frequency`
  / `m_extent` numbers from the game; their game-play semantics aren't
  fully documented, but higher = more abundant.

## Project layout

```
build/
  build.py                       entrypoint
  parsers/
    cfg.py                       recursive .cfg parser (handles length-N arrays)
    bspr.py                      sprite-atlas parser
  extract/
    catalog.py                   walk all configs into a unified catalog
    ores.py                      enrich ores with laser/smelt/locations
  render/
    pages.py                     orchestrates Jinja2 rendering
    templates/                   Jinja2 templates (base, index, category, …)
  world_to_distribution.json     planet-type metadata (hand-authored)
  requirements.txt
assets/
  style.css                      dark theme + tier colours
  search.js                      client-side fuzzy search
  data.json                      search manifest (generated)
  icons/                         per-item PNGs (generated)
data/
  catalog.json                   full intermediate (generated)
ores/, ingots/, tools/, …        per-item HTML (generated)
*.html                           category overviews + index (generated)
```

## Verification checklist (v1)

- [x] Open `index.html` in Firefox via `file://` — landing renders, search
  returns hits for "iron", "diamond".
- [x] `ores.html` shows ≥20 ores in a sortable table with tier colours.
- [x] `ores/res_iron_ore.html` shows tier 1, `m_mineUnit 0.7`, required
  laser MINING_LASER_0, smelt 8s/2 fuel → Iron Ingot.
- [x] `ores/res_diamond.html` shows tier 5, required laser MINING_LASER_4.
- [x] `tools/wep_mining_laser_3.html` shows `voxel_tier 4` and lists ores
  it can mine (T1–T4).
- [x] Cross-links (ore→ingot, ore→laser, ingot→ore) all resolve.
- [x] Disabling JS in the browser still renders every detail page (only
  search degrades).
- [x] `ls assets/icons/ | wc -l` ≥ 300.

## Adjacent project

[`../CubicOdysseyVault`](../CubicOdysseyVault/) — save-file backup tool;
the parsers in `CubicOdysseyVault.Core/SaveContent/` were the reference
for the BSPR and `.cfg` formats reused here.
