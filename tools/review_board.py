"""Prepare a review copy of an imported board with the designer's own rules restored, then run KiCad DRC on it.

The import keeps geometry but not rules (see README), so a DRC on the raw import checks against KiCad defaults.
Here the original values are put back first:
  Altium BLV.PcbDoc (Rules6): clearance 10 mil, min width 10 mil, hole-to-hole 10 mil, mask expansion 4 mil
    (the clearance rule ignores pad-to-pad inside a footprint; that switch is not restored here, see REVIEW.md)
  Eagle Qwiic_Button.brd (designrules): copper clearance 7 mil, min width 7 mil, min drill 15 mil, copper-dimension 7 mil
Usage: "C:/Program Files/KiCad/10.0/bin/python.exe" review_board.py altium|eagle <source> <out.kicad_pcb>
  <source>: the original .PcbDoc / .brd, or a corrected .kicad_pcb
"""
import json
import subprocess
import sys
from pathlib import Path

import pcbnew

CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
MIL = 0.0254
RULES = {
    "altium": dict(clearance=10 * MIL, track=10 * MIL, hole_to_hole=10 * MIL, mask=4 * MIL, edge=None, drill=None),
    "eagle": dict(clearance=7 * MIL, track=7 * MIL, hole_to_hole=None, mask=None, edge=7 * MIL, drill=15 * MIL),
}
kind, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
r = RULES[kind]
plugin = pcbnew.PCB_IO_MGR.ALTIUM_DESIGNER if kind == "altium" else pcbnew.PCB_IO_MGR.EAGLE
# A .kicad_pcb source is an already corrected import (reexport.py --fix-eagle); anything else goes through the importer
b = pcbnew.LoadBoard(str(src)) if src.suffix == ".kicad_pcb" else pcbnew.PCB_IO_MGR.Load(plugin, str(src))
moved = 0
for fp in b.GetFootprints():
    for it in [*fp.GraphicalItems(), *fp.GetFields()]:
        if it.GetLayer() < 0:
            it.SetLayer(pcbnew.Cmts_User)
            moved += 1
for it in [*b.GetDrawings(), *b.GetTracks()]:
    if it.GetLayer() < 0:
        it.SetLayer(pcbnew.Cmts_User)
        moved += 1
out.parent.mkdir(parents=True, exist_ok=True)
# Net classes live in the .kicad_pro in KiCad 10, and SaveBoard (which writes it) aborts on a plugin-loaded board:
# save the geometry first, reload it as a normal board, then set the rules and save board + project together.
pcbnew.PCB_IO_MGR.Save(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(out), b)
b = pcbnew.LoadBoard(str(out))
ds = b.GetDesignSettings()
mm = pcbnew.FromMM
ds.m_MinClearance = mm(r["clearance"])
ds.m_TrackMinWidth = mm(r["track"])
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetClearance(mm(r["clearance"]))
nc.SetTrackWidth(mm(r["track"]))
if r["hole_to_hole"]:
    ds.m_HoleToHoleMin = mm(r["hole_to_hole"])
if r["mask"] is not None:
    ds.m_SolderMaskExpansion = mm(r["mask"])
if r["edge"]:
    ds.m_CopperEdgeClearance = mm(r["edge"])
if r["drill"]:
    ds.m_MinThroughDrill = mm(r["drill"])
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(str(out), b)
assert out.with_suffix(".kicad_pro").exists(), "project file with the restored net class was not written"
rep = out.with_suffix(".drc.json")
subprocess.run([CLI, "pcb", "drc", "--severity-all", "--format", "json", "--units", "mm", "-o", str(rep), str(out)],
               capture_output=True, text=True)
d = json.load(open(rep, encoding="utf-8"))
from collections import Counter
print("moved off UNDEFINED:", moved)
print("violations:", Counter((v["type"], v["severity"]) for v in d["violations"]))
print("unconnected:", len(d["unconnected_items"]))
