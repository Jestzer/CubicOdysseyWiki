# Reverse-engineering Cubic Odyssey's `.glm` mesh format

Working notes from the first reverse-engineering pass. Goal: parse character
`.glm` files well enough to render bind-pose enemy thumbnails with the
matching diffuse skin applied.

## Status

- ✅ Rigid mesh format fully parses (verified on `simple_triangle.glm`).
- 🟡 Skinned character format partially parses — vertex stride and UV
     location are confirmed, but the position field and per-submesh
     index count are still open questions. Vertex point clouds don't yet
     plot to a recognisable shape.
- ❌ No rendering pipeline yet.

## File header (both variants)

```
+0x00  4B  magic 'glm' + version byte (0x05 on every file seen)
+0x04  4B  texture count N (uint32)
+0x08  N×24B  per-texture: 6 floats (looks like local bbox/transform)
+0x30  N×24B  per-texture: ASCII filename padded to 24 bytes (e.g. `donut_l.pvr\0` or `Male_Pirate_melee_D.pvr\0`)
```

For the pirate character file all 19 textures resolve to the same
`Male_Pirate_melee_D.pvr` — the duplicates probably represent draw-call
slots, not distinct materials.

## Rigid mesh — `data/models/objects/simple_triangle.glm` (836 bytes)

Layout after the header is straightforward:

```
+0x40   4B    0xDDDDDDDD separator/sentinel
+0x44   ~96B  identity-ish 4×4 matrices (likely transform + bbox)
+0xA8   4B    submesh-data header `04 00 01 03`
+0xAC   4B    index_count (uint32)  — 24 for triangle
+0xB0   4B    vertex_count (uint32) — 18 for triangle
+0xB4   16B   zero padding
+0xC4   vertex_count × 32B  vertex array
+VEND   4B    uint32 prefix (= 0)
+VEND+4 index_count × 2B    uint16 indices
+IEND   trailer (`6f 68 00 03` + zeros)
```

Vertex stride 32 bytes:

```
+ 0  vec3  position
+12  vec3  normal
+24  vec2  uv
```

Indices are unsigned 16-bit and form a flat triangle list
(`(i0,i1,i2)(i3,i4,i5)…`).

Verified: positions span a sensible bbox, UVs in [0,1], normals
unit-length-ish, indices in range.

## Skinned character — `data/models/character/male/bind_pose_pirate_melee.glm`

Header is the same `glm\x05` + 19 PVR strings (24 bytes each). After the
string table there's a different section layout:

```
+0x1F8   ~88B   floats — global transform / bbox
+0x250   19 × 0x88B    per-submesh metadata records
+0xC68   4B            data-section header `04 00 01 03`
+0xC6C   24B           zeros
+0xC84   ... mesh data, one block per submesh, sequentially
```

### Per-submesh metadata record (0x88 = 136 bytes)

```
+0x00  4B    header bytes `04 00 01 16`
+0x04  4B    count A (uint32)         — equals count B for every record
+0x08  4B    count B (uint32)
+0x0C  20B   zeros
+0x20  64B   identity-ish 4×4 transform matrix (with sign flip on Z)
+0x60  16B   four floats (look like bbox min)
+0x70  8B    two floats (look like bbox extent)
+0x78  16B   four floats (look like bbox min, repeated)
```

The 19 counts for `bind_pose_pirate_melee.glm`:
1914, 129, 444, 648, 1224, 648, 444, 129, 768, 12, 6, 12, 6, 396, 300, 498, 498, 300, 396 — total 8772.

### Submesh data layout

After the header at 0xC68 the data section appears to be: for each
submesh, vertex array → index array → null-terminated label →
4-byte-aligned padding. Labels recovered in order: `oh_body1`,
`oh_arm3_left`, `oh_arm2_left`, `oh_arm1_left`, `oh_helmet`,
`oh_arm1_right`, `oh_arm2_right`, `oh_arm3_right`, `oh_body2`,
`oh_leg3_left`, `oh_leg2_left`, `oh_leg1_left`, `oh_leg1_right`,
`oh_leg2_right`, `oh_leg3_right` — 15 labels but 19 metadata records.
Discrepancy unresolved; could be 4 records share a mesh, or 4 records
are dummy/skeleton stubs.

### Vertex stride

**56 bytes.** Confirmed by detecting that the value at offset 0 of
vertex N reappears at offset 0 of vertex N+1 for several adjacent
vertices.

### Confirmed field

`+44  vec2  uv` — all 1914 UVs for submesh 0 fall in `[0, 1]`.

### Open questions on vertex layout

- **Position is unknown.** Parsing pos at offset 0 gives ranges
  `x∈[-0.08, 0.42] y∈[0.68, 1.44] z∈[-1, 1]` — looks like local mesh
  coords for a torso but the X range is asymmetric. Plotting as a 2D
  scatter doesn't form a recognisable body.
- Parsing pos at offset 36 gives `x∈[-2.4, 2.4] y∈[-3.4, 2.5]
  z∈[0, 1]` — Y range is implausibly tall (a body part wouldn't span
  6 units), and Z always in [0,1] suggests this overlaps the UV slot.
- Offsets 12-23 and 24-35 contain vec3-shaped data with magnitudes
  near 1.0 but not unit-length — possibly tangent / bitangent /
  packed-quaternion frame, not normals.
- Last 4 bytes (offset 52) of vertex 1913 are `00 00 01 00`, which
  reads cleanly as four `uint8` bone indices — strong hint there's
  skinning data packed somewhere in 36-55.

### Open question on index count

Metadata says submesh 0 has `a = b = 1914`. The actual byte distance
from end-of-vertex-array to start-of-label is 3824 = **1912 uint16
indices**. Off by 2. For submesh 1 (count 129) the byte math gives
exactly 129 indices, so the off-by-2 is specific to the biggest
submesh — possible explanation: a 4-byte primitive-type / restart-flag
header that I'm including in the index count.

## Suggested next steps when resuming

1. **Plot all submeshes together** with each candidate position field
   (and apply the per-submesh transform matrix from metadata) — a
   coherent character outline is the cheap signal for "got it".
2. **Try Y as up-axis.** Cubic Odyssey is voxel-cube engine; many use
   Y-up while bind poses are sometimes Z-up. Swapping axes may resolve
   the asymmetric body bbox.
3. **Check if the vertex layout matches a known format** (Quake MDL/GLM,
   id Tech, Unity skinned vertex, Source MDL). The 56-byte stride is
   common in Unity skinned meshes: pos(12)+norm(12)+tan(16)+uv(8)+
   boneIdx(4)+boneWt(4) = 56, where boneIdx is 4×u8 and boneWt is 4×u8
   normalised. Worth comparing byte-for-byte.
4. **Render with the rigid-format parser first.** Static objects like
   `pirate_decor1.glm` may use the simple format and yield a quick win
   for non-enemy visuals.
5. **Once positions are decoded**, write a small software rasteriser:
   project tris to screen, barycentric interpolate UVs, sample the DDS
   diffuse, write to PNG. Don't bother with lighting — flat texture is
   fine.

## Useful file offsets (pirate)

```
0x000   glm header
0x004   tex_count = 19
0x030   start of 19×24 byte texture strings
0x1F8   end of strings, start of global transform/bbox
0x250   start of 19 per-submesh metadata records (each 0x88)
0xC68   data-section header `04 00 01 03`
0xC84   start of submesh 0 vertex array (1914 × 56 bytes)
0x1AF34 start of submesh 0 index array
0x1BE24 start of `oh_body1\0` label
0x1BE30 start of submesh 1 vertex array
```

## Pivot if we don't crack it

If a second focused pass still doesn't yield a clean character render,
fall back to the team-coloured weapon-icon badge that we already have
the data for — every enemy has a `weapon_id` that resolves to an icon
in `assets/icons/`, and `team` gives us a colour. Cheap, ships in an
hour.
