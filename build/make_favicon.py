#!/usr/bin/env python3
"""Generate the wiki favicon: an isometric voxel cube that nods to the
game's blue/orange logo without ripping its art. Outputs:

    assets/favicon.svg     (primary, vector)
    assets/favicon-32.png  (modern browsers)
    assets/favicon-180.png (apple-touch-icon)
    assets/favicon.ico     (legacy fallback, packs 16/32/48)

Re-run any time after tweaking the colours below.
"""

from pathlib import Path

from PIL import Image, ImageDraw


# Palette — same names + values as in assets/style.css
TOP   = '#67b0ff'  # var(--accent)
LEFT  = '#ff9a4c'  # var(--accent-hot)
RIGHT = '#4ea1d3'  # var(--t3)
OUTLINE = '#0c0f14'  # var(--bg)


# Cube polygons in a 100x100 coordinate system. Three visible faces.
# Top is a flat diamond; left and right share the central vertical.
TOP_POINTS   = [(50,  8), (90, 30), (50, 52), (10, 30)]
LEFT_POINTS  = [(10, 30), (50, 52), (50, 92), (10, 68)]
RIGHT_POINTS = [(90, 30), (50, 52), (50, 92), (90, 68)]


def _scale(points, size):
    s = size / 100
    return [(round(x * s, 2), round(y * s, 2)) for x, y in points]


def render_png(size: int) -> Image.Image:
    """Draw the cube at `size`x`size`. We supersample 4x and downsample
    with LANCZOS so the diagonal edges stay crisp even at favicon sizes.
    """
    ss = size * 4
    img = Image.new('RGBA', (ss, ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outline_w = max(2, ss // 28)
    # Order matters: paint back→front to get correct overlap on the centre.
    draw.polygon(_scale(TOP_POINTS,   ss), fill=TOP,   outline=OUTLINE)
    draw.polygon(_scale(LEFT_POINTS,  ss), fill=LEFT,  outline=OUTLINE)
    draw.polygon(_scale(RIGHT_POINTS, ss), fill=RIGHT, outline=OUTLINE)
    # The PIL `outline` arg is 1px; thicken by stroking polygon edges as lines.
    for pts in (TOP_POINTS, LEFT_POINTS, RIGHT_POINTS):
        scaled = _scale(pts, ss)
        for i in range(len(scaled)):
            a = scaled[i]
            b = scaled[(i + 1) % len(scaled)]
            draw.line([a, b], fill=OUTLINE, width=outline_w)
    return img.resize((size, size), Image.LANCZOS)


SVG_TEMPLATE = '''\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img"
     aria-label="Cubic Odyssey wiki favicon">
    <g stroke="{outline}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round">
        <polygon points="50,8 90,30 50,52 10,30" fill="{top}"/>
        <polygon points="10,30 50,52 50,92 10,68" fill="{left}"/>
        <polygon points="90,30 50,52 50,92 90,68" fill="{right}"/>
    </g>
</svg>
'''


def write_svg(path: Path):
    path.write_text(SVG_TEMPLATE.format(top=TOP, left=LEFT, right=RIGHT,
                                         outline=OUTLINE), encoding='utf-8')


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    write_svg(out / 'favicon.svg')
    render_png(32).save(out / 'favicon-32.png', 'PNG', optimize=True)
    render_png(180).save(out / 'favicon-180.png', 'PNG', optimize=True)
    # ICO container with 16/32/48 packed
    render_png(48).save(
        out / 'favicon.ico',
        format='ICO',
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f'wrote favicon assets to {out}')


if __name__ == '__main__':
    main(Path(__file__).resolve().parent.parent / 'assets')
