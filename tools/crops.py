"""Crop images for the review reports: kicad-cli draws the layers to SVG in board coordinates (mm), the SVG viewBox
is moved onto the finding, CairoSVG rasterises it, and each reported location gets a red ring.

Usage: crops.py <board.kicad_pcb> <spec.json> <out_dir>
  spec.json: [{"name": "u2_mask", "layers": "F.Cu,F.Mask,Edge.Cuts", "at": [x, y], "half": 3.0,
               "marks": [[x, y], ...]}, ...]          coordinates as KiCad shows them (mm, y down)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw

CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
PX = 60          # px per mm

board, spec, out = Path(sys.argv[1]), json.load(open(sys.argv[2], encoding="utf-8")), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
svgs = {}
for c in spec:
    if c["layers"] not in svgs:
        f = out / ("_layers%d.svg" % len(svgs))
        r = subprocess.run([CLI, "pcb", "export", "svg", "--mode-single", "--exclude-drawing-sheet", "--page-size-mode", "0",
                            "--layers", c["layers"], "-o", str(f), str(board)], capture_output=True, text=True)
        assert r.returncode == 0 and f.exists(), r.stderr
        svgs[c["layers"]] = f.read_text(encoding="utf-8")
        f.unlink()
    x, y, h = c["at"][0], c["at"][1], c["half"]
    head = 'width="%gmm" height="%gmm" viewBox="%g %g %g %g"' % (2 * h, 2 * h, x - h, y - h, 2 * h, 2 * h)
    svg, n = re.subn(r'width="[^"]*mm" height="[^"]*mm" viewBox="[^"]*"', head, svgs[c["layers"]], count=1)
    assert n == 1, "SVG header not found"
    png = out / (c["name"] + ".png")
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png), output_width=int(2 * h * PX),
                     output_height=int(2 * h * PX))
    im = Image.open(png).convert("RGBA")
    bg = Image.new("RGBA", im.size, "white")
    bg.alpha_composite(im)
    d = ImageDraw.Draw(bg)
    for mx, my in c.get("marks", []):
        px, py = (mx - x + h) * PX, (my - y + h) * PX
        d.ellipse((px - 0.45 * PX, py - 0.45 * PX, px + 0.45 * PX, py + 0.45 * PX), outline="red", width=3)
    d.line((10, bg.height - 12, 10 + PX, bg.height - 12), fill="black", width=3)        # 1 mm scale bar
    d.text((14 + PX, bg.height - 22), "1 mm", fill="black")
    d.text((8, 6), "%s  centre (%.2f, %.2f) mm" % (c["name"], x, y), fill="black")
    bg.convert("RGB").save(png)
    print("wrote", png)
