"""Load an imported design with KiCad's own importer, fill its zones, save it, and write Gerbers + drill.

Usage: "C:/Program Files/KiCad/10.0/bin/python.exe" reexport.py <source.PcbDoc|source.brd> <out_dir>
The board is loaded from the ORIGINAL file through pcbnew's Altium / Eagle plugin (same code path as
`kicad-cli pcb import`), so the comparison does not depend on a saved .kicad_pcb that pcbnew might refuse to reopen.
"""
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
for it in [*b.GetDrawings(), *b.GetTracks()]:
    if it.GetLayer() < 0:          # UNDEFINED_LAYER is -1, but the Eagle importer leaves -2
        it.SetLayer(pcbnew.Cmts_User)
        moved.append(f"board:{it.GetClass()}")
print("items moved off UNDEFINED:", len(moved), sorted(set(moved))[:12])
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcb = out / (src.stem + "_filled.kicad_pcb")
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
print("saved", pcb, "and", len(list(ger.iterdir())), "fab files")
