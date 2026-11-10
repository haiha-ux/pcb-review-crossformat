"""Write the Gerber pair lists (original vs KiCad re-export) that gerber_xor.py compares. Run from the repo root."""
import json
from pathlib import Path

R = Path.cwd()
a = R / "samples/altium_blv/original/gerber"
k = R / "samples/altium_blv/kicad/reexport/gerber"
blv = {"outline": [a / "BLV.GKO", k / "BLV_filled-Edge_Cuts.gbr"], "layers": {
    "F.Cu": [a / "BLV.GTL", k / "BLV_filled-Top Layer.gbr"], "B.Cu": [a / "BLV.GBL", k / "BLV_filled-Bottom Layer.gbr"],
    "F.Mask": [a / "BLV.GTS", k / "BLV_filled-Top Solder.gbr"], "B.Mask": [a / "BLV.GBS", k / "BLV_filled-Bottom Solder.gbr"],
    "F.Silk": [a / "BLV.GTO", k / "BLV_filled-Top Overlay.gbr"],
    "B.Silk": [a / "BLV.GBO", k / "BLV_filled-Bottom Overlay.gbr"]}}
q = R / "samples/eagle_qwiic_button/original/gerber"
e = R / "samples/eagle_qwiic_button/kicad/reexport_panel/gerber"
names = {f.name for f in e.iterdir()}


def pick(*cands):
    for c in cands:
        if c in names:
            return e / c
    raise SystemExit("none of %s in %s" % (cands, sorted(names)))


qb = {"outline": [q / "Qwiic_Button-Panel.GKO", pick("Qwiic_Button-Panel_filled-Edge_Cuts.gbr")], "layers": {
    "F.Cu": [q / "Qwiic_Button-Panel.GTL", pick("Qwiic_Button-Panel_filled-F_Cu.gbr")],
    "B.Cu": [q / "Qwiic_Button-Panel.GBL", pick("Qwiic_Button-Panel_filled-B_Cu.gbr")],
    "F.Mask": [q / "Qwiic_Button-Panel.GTS", pick("Qwiic_Button-Panel_filled-F_Mask.gbr")],
    "B.Mask": [q / "Qwiic_Button-Panel.GBS", pick("Qwiic_Button-Panel_filled-B_Mask.gbr")],
    "F.Silk": [q / "Qwiic_Button-Panel.GTO", pick("Qwiic_Button-Panel_filled-F_Silkscreen.gbr")],
    "B.Silk": [q / "Qwiic_Button-Panel.GBO", pick("Qwiic_Button-Panel_filled-B_Silkscreen.gbr")]}}
for name, cfg in (("blv", blv), ("qwiic_panel", qb)):
    for pair in [cfg["outline"], *cfg["layers"].values()]:
        for f in pair:
            assert Path(f).exists(), f
    json.dump(json.loads(json.dumps(cfg, default=lambda p: Path(p).as_posix())), open(f"results/pairs_{name}.json", "w"),
              indent=1)
    print("wrote results/pairs_%s.json" % name)
