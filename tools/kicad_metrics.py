"""Counts from the imported KiCad board, the "after" side of the fidelity table (KiCad's own Python, pcbnew).

Usage: "C:/Program Files/KiCad/10.0/bin/python.exe" kicad_metrics.py <board.kicad_pcb | board.brd>   -> JSON on stdout
A .brd is loaded through KiCad's Eagle importer in memory: an imported Eagle board that kept items on the UNDEFINED
layer cannot be re-opened from its .kicad_pcb by pcbnew, so the counts are taken before saving.
"""
import collections
import json
import sys

import pcbnew

path = sys.argv[1]
b = (pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.EAGLE, path) if path.lower().endswith(".brd")
     else pcbnew.LoadBoard(path))
mm = 1e6
copper = [l for l in b.GetEnabledLayers().CuStack()]
tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
arcs = [t for t in b.GetTracks() if t.GetClass() == "PCB_ARC"]
vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
length = collections.Counter()
for t in tracks + arcs:
    length[b.GetLayerName(t.GetLayer())] += t.GetLength() / mm
slength = collections.Counter()
for t in tracks:
    slength[b.GetLayerName(t.GetLayer())] += t.GetLength() / mm
undefined = (sum(1 for d in b.GetDrawings() if d.GetLayer() < 0)
             + sum(1 for fp in b.GetFootprints() for g in fp.GraphicalItems() if g.GetLayer() < 0))
pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
zones = [z for z in b.Zones() if not z.GetIsRuleArea()]
rule_areas = [z for z in b.Zones() if z.GetIsRuleArea()]
nets = [n for n in b.GetNetInfo().NetsByName().keys() if str(n) and not str(n).startswith("unconnected-")]
ds = b.GetDesignSettings()
bb = b.GetBoardEdgesBoundingBox()
texts = [d for d in b.GetDrawings() if d.GetClass() in ("PCB_TEXT", "PCB_TEXTBOX")]
classes = ds.m_NetSettings.GetNetclasses() if hasattr(ds.m_NetSettings, "GetNetclasses") else {}
out = {
    "copper_layers": len(copper),
    "board_mm": [round(bb.GetWidth() / mm, 3), round(bb.GetHeight() / mm, 3)],
    "footprints": len(b.GetFootprints()),
    "footprints_without_pads": sorted(fp.GetReference() for fp in b.GetFootprints() if not len(fp.Pads())),
    "nets": len(nets),
    "pads": len(pads),
    "pads_by_attribute": dict(collections.Counter({pcbnew.PAD_ATTRIB_PTH: "PTH", pcbnew.PAD_ATTRIB_SMD: "SMD",
                                                   pcbnew.PAD_ATTRIB_CONN: "CONN", pcbnew.PAD_ATTRIB_NPTH: "NPTH"}
                                                  [p.GetAttribute()] for p in pads)),
    "vias": len(vias),
    "tracks": len(tracks),
    "arcs": len(arcs),
    "track_length_mm_per_layer": {k: round(v, 2) for k, v in sorted(length.items())},
    "straight_track_length_mm_per_layer": {k: round(v, 2) for k, v in sorted(slength.items())},
    "items_on_undefined_layer": undefined,
    "zones": len(zones),
    "zones_per_layer": dict(collections.Counter(b.GetLayerName(z.GetFirstLayer()) for z in zones)),
    "rule_areas": len(rule_areas),
    "board_texts": len(texts),
    "netclasses": sorted(str(k) for k in classes.keys()) if hasattr(classes, "keys") else [],
    "rules_mm": {"min_clearance": ds.m_MinClearance / mm, "min_track": ds.m_TrackMinWidth / mm,
                 "default_clearance": ds.m_NetSettings.GetDefaultNetclass().GetClearance() / mm,
                 "default_track": ds.m_NetSettings.GetDefaultNetclass().GetTrackWidth() / mm,
                 "solder_mask_expansion": ds.m_SolderMaskExpansion / mm},
}
print(json.dumps(out, indent=1))
