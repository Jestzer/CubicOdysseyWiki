"""Walk the game's data/configs and assemble a unified catalog of items,
voxels, weapons, recipes, distributions, biomes, and worlds.

All records are returned as plain dicts so they JSON-serialize cleanly.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from parsers.cfg import parse_file


@dataclass
class Catalog:
    items: Dict[str, dict] = field(default_factory=dict)
    items_by_id: Dict[int, dict] = field(default_factory=dict)
    items_by_file: Dict[str, dict] = field(default_factory=dict)
    voxels: Dict[str, dict] = field(default_factory=dict)
    ranged_weapons: Dict[str, dict] = field(default_factory=dict)
    melee_weapons: Dict[str, dict] = field(default_factory=dict)
    recipes: List[dict] = field(default_factory=list)
    recipes_by_input: Dict[str, dict] = field(default_factory=dict)
    crafting_recipes: List[dict] = field(default_factory=list)
    distributions: Dict[str, dict] = field(default_factory=dict)
    biomes: Dict[str, dict] = field(default_factory=dict)
    worlds: Dict[str, dict] = field(default_factory=dict)
    game_root: Optional[Path] = None

    @classmethod
    def load(cls, game_root: Path) -> 'Catalog':
        cat = cls(game_root=game_root)
        cfg = game_root / 'data' / 'configs'
        cat._load_items(cfg / 'items')
        cat._load_voxels(cfg / 'voxels')
        cat._load_weapons(cfg / 'rangedweapons', cat.ranged_weapons)
        cat._load_weapons(cfg / 'meleeweapons', cat.melee_weapons)
        cat._load_furnace(cfg / 'furnace')
        cat._load_recipes(cfg / 'recipes')
        cat._load_dir_as_dict(cfg / 'voxeldistributions', cat.distributions)
        cat._load_dir_as_dict(cfg / 'worldbiomes', cat.biomes)
        cat._load_dir_as_dict(cfg / 'worlds', cat.worlds)
        return cat

    def _load_items(self, items_dir: Path):
        for path in sorted(items_dir.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict) or 'identifier' not in data:
                continue
            ident = data['identifier']
            self.items[ident] = data
            self.items_by_file[path.stem] = data
            iid = data.get('id')
            if isinstance(iid, int):
                self.items_by_id[iid] = data

    def _load_voxels(self, voxels_dir: Path):
        for path in sorted(voxels_dir.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict) or 'name' not in data:
                continue
            self.voxels[data['name']] = data

    def _load_weapons(self, weapons_dir: Path, target: Dict[str, dict]):
        if not weapons_dir.is_dir():
            return
        for path in sorted(weapons_dir.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict):
                continue
            target[path.stem] = data

    def _load_furnace(self, furnace_dir: Path):
        for path in sorted(furnace_dir.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict) or 'input' not in data:
                continue
            data['_file'] = path.stem
            self.recipes.append(data)
            self.recipes_by_input[data['input']] = data

    def _load_recipes(self, recipes_dir: Path):
        if not recipes_dir.is_dir():
            return
        for path in sorted(recipes_dir.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict) or 'craftedObject' not in data:
                continue
            data['_file'] = path.stem
            self.crafting_recipes.append(data)

    def recipes_using(self, item_identifier: str) -> List[dict]:
        out = []
        for r in self.crafting_recipes:
            for inp in (r.get('inputItems') or []):
                if isinstance(inp, dict) and inp.get('item') == item_identifier:
                    out.append(r)
                    break
        return out

    def _load_dir_as_dict(self, d: Path, target: Dict[str, dict]):
        if not d.is_dir():
            return
        for path in sorted(d.glob('*.cfg')):
            data = parse_file(path)
            if not isinstance(data, dict):
                continue
            target[path.stem] = data

    # Convenience accessors ------------------------------------------------

    def item_by_identifier(self, identifier: str) -> Optional[dict]:
        return self.items.get(identifier)

    def voxel_by_name(self, name: str) -> Optional[dict]:
        return self.voxels.get(name)

    def recipe_for_input(self, input_identifier: str) -> Optional[dict]:
        return self.recipes_by_input.get(input_identifier)

    def ore_voxels(self) -> Dict[str, dict]:
        return {n: v for n, v in self.voxels.items()
                if v.get('m_category') == 'E_VCAT_ORES'}

    def items_of_type(self, *types: str) -> Dict[str, dict]:
        return {k: v for k, v in self.items.items()
                if v.get('type') in types}

    def ingot_items(self) -> Dict[str, dict]:
        out = {}
        for ident, item in self.items.items():
            if item.get('type') == 'PROCESSED_ORE' or ident.endswith('.ingot'):
                out[ident] = item
        return out


if __name__ == '__main__':
    import sys
    import json
    root = Path(sys.argv[1] if len(sys.argv) > 1
                else '/run/media/james/SSD/Program Files (x86)/Steam/steamapps/common/Cubic Odyssey')
    cat = Catalog.load(root)
    print(f'items:         {len(cat.items)}')
    print(f'voxels:        {len(cat.voxels)}')
    print(f'ore voxels:    {len(cat.ore_voxels())}')
    print(f'ranged wpns:   {len(cat.ranged_weapons)}')
    print(f'melee wpns:    {len(cat.melee_weapons)}')
    print(f'recipes:       {len(cat.recipes)}')
    print(f'distributions: {len(cat.distributions)}')
    print(f'biomes:        {len(cat.biomes)}')
    print(f'worlds:        {len(cat.worlds)}')
    print(f'ingots:        {len(cat.ingot_items())}')
    print('--- iron ---')
    iron_v = cat.voxel_by_name('Iron')
    iron_i = cat.item_by_identifier('res.iron.ore')
    iron_r = cat.recipe_for_input('res.iron.ore')
    print(' voxel tier:', iron_v.get('m_tier'))
    print(' item id:', iron_i.get('id'), 'inv_frame:', iron_i.get('inv_frame'))
    print(' recipe:', iron_r.get('output0'), 'in', iron_r.get('cookTime'), 'sec')
