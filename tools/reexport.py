"""Load an imported design with KiCad's own importer, fill its zones, save it, and write Gerbers + drill.

Usage: "C:/Program Files/KiCad/10.0/bin/python.exe" reexport.py <source.PcbDoc|source.brd> <out_dir> [--fix-eagle]
--fix-eagle restores the STAND-OFF copper keep-outs and trims NPTH pads to their drill (see README).
The board is loaded from the ORIGINAL file through pcbnew's Altium / Eagle plugin (same code path as
`kicad-cli pcb import`), so the comparison does not depend on a saved .kicad_pcb that pcbnew might refuse to reopen.
"""
import math
import subprocess
import sys
from pathlib import Path

import pcbnew

CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
kind = pcbnew.PCB_IO_MGR.ALTIUM_DESIGNER if src.suffix.lower() == ".pcbdoc" else pcbnew.PCB_IO_MGR.EAGLE
b = pcbnew.PCB_IO_MGR.Load(kind, str(src))
# Items the importer could not map land on UNDEFINED, and kicad-cli then refuses the saved board. Park them on
# Cmts.User (no fab output) and say how many, so the fidelity table can list them as lost.
moved = []
for fp in b.GetFootprints():
    for it in [*fp.GraphicalItems(), fp.Reference(), fp.Value(), *fp.GetFields()]:
        if it.GetLayer() < 0:          # UNDEFINED_LAYER is -1, but the Eagle importer leaves -2
            it.SetLayer(pcbnew.Cmts_User)
            moved.append(f"{fp.GetReference()}:{it.GetClass()}")
board_lines = []
for it in [*b.GetDrawings(), *b.GetTracks()]:
    if it.GetLayer() < 0:          # UNDEFINED_LAYER is -1, but the Eagle importer leaves -2
        it.SetLayer(pcbnew.Cmts_User)
        moved.append(f"board:{it.GetClass()}")
        if it.GetClass() == "PCB_SHAPE" and it.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            board_lines.append(it)
print("items moved off UNDEFINED:", len(moved), sorted(set(moved))[:12])
fix = "--fix-eagle" in sys.argv
EDGE = pcbnew.FromMM(7 * 0.0254)       # Eagle mdCopperDimension, which also applies to the Milling layer 46


def keepout(name, pts):
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu)
    ls.AddLayer(pcbnew.B_Cu)
    z.SetLayerSet(ls)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(int(x), int(y))
    z.SetZoneName(name)
    b.Add(z)


if fix:
    # Import losses that change copper, put back by hand as a reviewer would:
    # 1. tRestrict/bRestrict rings of the STAND-OFF package (r 1.854 mm, 0.2032 mm wide) -> copper keep-out discs
    # 2. Eagle <hole>s become NPTH pads larger than their drill, which KiCad plots as copper rings -> no copper
    # 3. copper-to-edge 7 mil; 4. panel V-score lines (Eagle Milling layer) -> keep-out strips of the same pull-back
    for s in board_lines:          # only the panel has these: the 8 V-score lines
        s.SetLayer(pcbnew.User_1)
        a, e, h = s.GetStart(), s.GetEnd(), s.GetWidth() / 2 + EDGE
        if a.x == e.x:
            keepout("v-score", [(a.x - h, min(a.y, e.y)), (a.x + h, min(a.y, e.y)), (a.x + h, max(a.y, e.y)), (a.x - h, max(a.y, e.y))])
        else:
            assert a.y == e.y, "V-score line is not axis-aligned"
            keepout("v-score", [(min(a.x, e.x), a.y - h), (max(a.x, e.x), a.y - h), (max(a.x, e.x), a.y + h), (min(a.x, e.x), a.y + h)])
    R = pcbnew.FromMM(1.854 + 0.2032 / 2)
    added = shrunk = 0
    for fp in b.GetFootprints():
        if fp.GetFPIDAsString().split(":")[-1] == "STAND-OFF":
            c = fp.GetPosition()
            keepout("restrict " + fp.GetReference(),
                    [(c.x + R * math.cos(2 * math.pi * i / 64), c.y + R * math.sin(2 * math.pi * i / 64)) for i in range(64)])
            added += 1
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and p.GetSizeX() > p.GetDrillSizeX():
                ls = p.GetLayerSet()      # keep the mask openings, drop only the copper
                ls.RemoveLayer(pcbnew.F_Cu)
                ls.RemoveLayer(pcbnew.B_Cu)
                p.SetLayerSet(ls)
                shrunk += 1
    b.GetDesignSettings().m_CopperEdgeClearance = EDGE   # import left the 0.5 mm default
    print("fix: V-score strips", len(board_lines), "keep-out discs", added, "NPTH pads without copper", shrunk)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcb = out / (src.stem + ("_fixed" if fix else "_filled") + ".kicad_pcb")
pcbnew.PCB_IO_MGR.Save(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(pcb), b)   # SaveBoard aborts on a plugin-loaded board
ger = out / "gerber"
ger.mkdir(exist_ok=True)
for f in ger.iterdir():
    f.unlink()
r = subprocess.run([CLI, "pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
                    "--no-protel-ext", "-o", str(ger) + "\\", str(pcb)], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
r = subprocess.run([CLI, "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
                    "-o", str(ger) + "\\", str(pcb)], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
assert pcbnew.LoadBoard(str(pcb)) is not None, "saved board does not reopen"
print("saved", pcb, "(reopens) and", len(list(ger.iterdir())), "fab files")
