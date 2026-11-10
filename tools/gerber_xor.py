"""Compare two Gerber sets layer by layer: the original fab output and the one KiCad writes after importing the design.

Each layer is drawn by gerbonara (an independent Gerber reader, not KiCad), shifted so the board outline's lower-left
corner sits at (0, 0), rasterised at RES px/mm and XORed. Reports, per layer: copper area in each set, area that is in
one set but not the other, and the largest differing blob; writes a diff image (red = only in the original, blue =
only in the re-export).

Usage: gerber_xor.py <pairs.json> <out_dir>
  pairs.json: {"outline": ["orig/x.GKO", "kicad/x-Edge_Cuts.gm1"],
               "layers": {"F.Cu": ["orig/x.GTL", "kicad/x-F_Cu.gtl"], ...}}
Runs gerbonara inside the venv given by GERBONARA_PY (default: the current Python) and rasterises here.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import cairosvg
import numpy as np
from PIL import Image

RES = 20.0          # px per mm -> 0.05 mm per pixel
GERBONARA_PY = os.environ.get("GERBONARA_PY", sys.executable)

STAGE1 = r'''
import json, sys
from gerbonara import GerberFile
from gerbonara.utils import MM
cfg = json.loads(sys.argv[1]); out = sys.argv[2]; M = float(sys.argv[3])
def bbox(p):
    (x0, y0), (x1, y1) = GerberFile.open(p).bounding_box(MM)
    return float(x0), float(y0), float(x1), float(y1)
res = {}
W = H = 0.0
for idx in (0, 1):
    x0, y0, x1, y1 = bbox(cfg["outline"][idx])
    W, H = max(W, x1 - x0), max(H, y1 - y0)
for side, idx in (("a", 0), ("b", 1)):
    x0, y0, x1, y1 = bbox(cfg["outline"][idx])
    res[side] = {"outline": [x0, y0, x1, y1], "layers": {}}
    for name, files in list(cfg["layers"].items()) + [("Outline", cfg["outline"])]:
        g = GerberFile.open(files[idx])
        g.offset(-x0, -y0, MM)
        svg = g.to_svg(force_bounds=((-M, -M), (W + M, H + M)), fg="black", bg="white")
        path = f"{out}/{side}_{name.replace('.', '_')}.svg"
        open(path, "w", encoding="utf-8").write(str(svg))
        res[side]["layers"][name] = path
print(json.dumps(res))
'''


MARGIN = 12.0       # mm of canvas around the board, so the alignment shift never pushes copper off the image


def raster(svg, w_mm, h_mm):
    png = cairosvg.svg2png(url=svg, output_width=int(round((w_mm + 2 * MARGIN) * RES)),
                           output_height=int(round((h_mm + 2 * MARGIN) * RES)))
    from io import BytesIO
    im = Image.open(BytesIO(png)).convert("RGBA")
    white = Image.new("RGBA", im.size, (255, 255, 255, 255))    # cairosvg ignores the CSS background: transparent
    a = np.array(Image.alpha_composite(white, im).convert("L"))
    return a < 128                                   # True = copper (drawn black on white)


def blobs(mask):
    import cv2
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted(((int(s[cv2.CC_STAT_AREA]), int(s[0]), int(s[1]), int(s[2]), int(s[3])) for s in stats[1:]), reverse=True)


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([GERBONARA_PY, "-c", STAGE1, json.dumps(cfg), str(out), str(MARGIN)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    st = json.loads(r.stdout.strip().splitlines()[-1])
    oa, ob = st["a"]["outline"], st["b"]["outline"]
    wa, ha, wb, hb = oa[2] - oa[0], oa[3] - oa[1], ob[2] - ob[0], ob[3] - ob[1]
    report = {"outline_mm": {"original": [round(wa, 3), round(ha, 3)], "reexport": [round(wb, 3), round(hb, 3)]},
              "res_mm_per_px": 1 / RES, "layers": {}}
    w, h = max(wa, wb), max(ha, hb)
    px_area = (1 / RES) ** 2
    import cv2
    # The two sets need not share an origin or an outline (Altium's GKO is a keep-out layer, a panel frame can differ),
    # so register them on the top copper itself: phase correlation gives the translation, applied to every layer.
    ref_layer = "F.Cu" if "F.Cu" in cfg["layers"] else list(cfg["layers"])[0]
    fa = raster(st["a"]["layers"][ref_layer], w, h).astype(np.float32)
    fb = raster(st["b"]["layers"][ref_layer], w, h).astype(np.float32)
    (dx, dy), resp = cv2.phaseCorrelate(fb, fa)
    report["alignment"] = {"on_layer": ref_layer, "shift_mm": [round(dx / RES, 3), round(-dy / RES, 3)],
                           "phase_correlation_response": round(float(resp), 3)}
    shift = np.float32([[1, 0, round(dx)], [0, 1, round(dy)]])

    def moved(m):
        return cv2.warpAffine(m.astype(np.uint8), shift, (m.shape[1], m.shape[0]), flags=cv2.INTER_NEAREST).astype(bool)
    for name in list(cfg["layers"]) + ["Outline"]:
        a = raster(st["a"]["layers"][name], w, h)
        b = moved(raster(st["b"]["layers"][name], w, h))
        only_a, only_b = a & ~b, b & ~a
        # a one-pixel disagreement along every edge is rasterisation noise; open the masks before measuring
        import cv2
        k = np.ones((3, 3), np.uint8)
        oa_ = cv2.morphologyEx(only_a.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
        ob_ = cv2.morphologyEx(only_b.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
        img = np.full(a.shape + (3,), 255, np.uint8)
        img[a | b] = (200, 200, 200)
        img[oa_] = (220, 0, 0)
        img[ob_] = (0, 0, 220)
        Image.fromarray(img).save(out / f"diff_{name.replace('.', '_')}.png")
        ba, bb = blobs(oa_), blobs(ob_)
        def big(bl):
            if not bl:
                return None
            area, x, y, wpx, hpx = bl[0]
            return {"area_mm2": round(area * px_area, 3), "at_mm": [round((x + wpx / 2) / RES - MARGIN, 2),
                                                                    round(h + MARGIN - (y + hpx / 2) / RES, 2)]}
        report["layers"][name] = {
            "area_original_mm2": round(a.sum() * px_area, 2), "area_reexport_mm2": round(b.sum() * px_area, 2),
            "only_in_original_mm2": round(oa_.sum() * px_area, 3), "only_in_reexport_mm2": round(ob_.sum() * px_area, 3),
            "largest_only_original": big(ba), "largest_only_reexport": big(bb)}
    json.dump(report, open(out / "xor_report.json", "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
