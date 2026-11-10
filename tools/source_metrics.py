"""Counts taken straight from the original design file, without KiCad, as the "before" side of the fidelity table.

Altium .PcbDoc (OLE compound file): every <Name>6/Header stream holds the record count of <Name>6/Data. Tracks6 is
decoded record by record (layout as in KiCad's altium_parser_pcb.cpp ATRACK6: layer u8, flags1 u8, flags2 u8,
net u16, polygon u16, component u16, 4 skipped bytes, start x/y i32, end x/y i32, width i32; 10000 units = 1 mil)
so free copper tracks can be separated from polygon-pour tracks and footprint graphics.
Eagle .brd (XML): elements, signals, vias, wires per layer with length, polygons, holes, design rules.

Usage: source_metrics.py <file.PcbDoc|file.brd>   -> JSON on stdout
"""
import json
import math
import struct
import sys
import xml.etree.ElementTree as ET

MIL_UNITS = 10000.0
MM_PER_UNIT = 0.0254 / MIL_UNITS
ALTIUM_TOP, ALTIUM_BOTTOM = 1, 32


def altium(path):
    import olefile
    o = olefile.OleFileIO(path)
    counts = {}
    for e in o.listdir():
        if len(e) == 2 and e[1] == "Header" and o.get_size("/".join(e)) == 4:
            counts[e[0]] = struct.unpack("<I", o.openstream("/".join(e)).read())[0]
    data = o.openstream("Tracks6/Data").read()
    i, n = 0, 0
    length = {"free_top": 0.0, "free_bottom": 0.0}
    kinds = {"free_copper": 0, "polygon_member": 0, "in_footprint": 0, "other_layers": 0, "keepout": 0}
    while i < len(data):
        rtype = data[i]
        ln = struct.unpack_from("<I", data, i + 1)[0]
        rec = data[i + 5:i + 5 + ln]
        i += 5 + ln
        n += 1
        assert rtype == 4, ("unexpected record type in Tracks6", rtype, n)
        layer, _f1, f2 = rec[0], rec[1], rec[2]
        _net, poly, comp = struct.unpack_from("<HHH", rec, 3)
        x1, y1, x2, y2, _w = struct.unpack_from("<iiiii", rec, 13)
        seg = math.hypot(x2 - x1, y2 - y1) * MM_PER_UNIT
        if f2 == 2:
            kinds["keepout"] += 1
        elif layer not in (ALTIUM_TOP, ALTIUM_BOTTOM):
            kinds["other_layers"] += 1
        elif comp != 0xFFFF:
            kinds["in_footprint"] += 1
        elif poly != 0xFFFF:
            kinds["polygon_member"] += 1
        else:
            kinds["free_copper"] += 1
            length["free_top" if layer == ALTIUM_TOP else "free_bottom"] += seg
    assert n == counts.get("Tracks6", n), ("Tracks6 record count disagrees with its header", n, counts.get("Tracks6"))
    # Arcs6, AARC6 in the same parser: same 13-byte head, then centre x/y i32, radius i32, start/end angle f64, width
    data = o.openstream("Arcs6/Data").read()
    i, n = 0, 0
    akinds = dict.fromkeys(kinds, 0)
    alen = {"free_top": 0.0, "free_bottom": 0.0}
    while i < len(data):
        rtype = data[i]
        ln = struct.unpack_from("<I", data, i + 1)[0]
        rec = data[i + 5:i + 5 + ln]
        i += 5 + ln
        n += 1
        assert rtype == 1, ("unexpected record type in Arcs6", rtype, n)
        layer, _f1, f2 = rec[0], rec[1], rec[2]
        _net, poly, comp = struct.unpack_from("<HHH", rec, 3)
        _cx, _cy, r = struct.unpack_from("<iii", rec, 13)
        a0, a1 = struct.unpack_from("<dd", rec, 25)
        sweep = (a1 - a0) % 360 or 360
        if f2 == 2:
            akinds["keepout"] += 1
        elif layer not in (ALTIUM_TOP, ALTIUM_BOTTOM):
            akinds["other_layers"] += 1
        elif comp != 0xFFFF:
            akinds["in_footprint"] += 1
        elif poly != 0xFFFF:
            akinds["polygon_member"] += 1
        else:
            akinds["free_copper"] += 1
            alen["free_top" if layer == ALTIUM_TOP else "free_bottom"] += r * MM_PER_UNIT * math.radians(sweep)
    assert n == counts.get("Arcs6", n), ("Arcs6 record count disagrees with its header", n, counts.get("Arcs6"))
    return {"format": "Altium PcbDoc", "record_counts": {k: counts[k] for k in sorted(counts) if counts[k]},
            "tracks6_by_kind": kinds, "free_track_length_mm": {k: round(v, 2) for k, v in length.items()},
            "arcs6_by_kind": akinds, "free_arc_length_mm": {k: round(v, 2) for k, v in alen.items()}}


def eagle(path):
    root = ET.parse(path).getroot()
    board = root.find("drawing/board")
    layers = {l.get("number"): l.get("name") for l in root.iter("layer")}
    sig = board.find("signals")
    wires_len, wires_n, vias, polys = {}, {}, 0, 0
    for s in sig.findall("signal"):
        for w in s.findall("wire"):
            ln = layers.get(w.get("layer"), w.get("layer"))
            x1, y1, x2, y2 = (float(w.get(k)) for k in ("x1", "y1", "x2", "y2"))
            d = math.hypot(x2 - x1, y2 - y1)
            curve = float(w.get("curve", "0") or 0)
            if curve:                                   # arc: chord d, angle curve -> arc length
                th = math.radians(abs(curve))
                d = d * th / (2 * math.sin(th / 2))
            wires_len[ln] = wires_len.get(ln, 0.0) + d
            wires_n[ln] = wires_n.get(ln, 0) + 1
        vias += len(s.findall("via"))
        polys += len(s.findall("polygon"))
    elements = board.find("elements").findall("element")
    plain = board.find("plain")
    rules = {p.get("name"): p.get("value") for p in board.iter("param")
             if p.get("name") in ("mdWireWire", "mdWirePad", "mdWireVia", "mdPadPad", "mdCopperDimension",
                                  "msWidth", "msDrill", "rlMinViaOuter", "mdSmdSmd", "slThermalIsolate")}
    return {"format": "Eagle brd", "eagle_version": root.get("version"), "elements": len(elements),
            "signals": len(sig.findall("signal")),
            "signals_with_connections": sum(1 for s in sig.findall("signal") if len(s.findall("contactref")) >= 2),
            "vias": vias, "polygons": polys, "plain_holes": len(plain.findall("hole")),
            "plain_texts": len(plain.findall("text")),
            "wires_per_layer": wires_n, "wire_length_mm_per_layer": {k: round(v, 2) for k, v in wires_len.items()},
            "design_rules": rules}


if __name__ == "__main__":
    p = sys.argv[1]
    print(json.dumps(altium(p) if p.lower().endswith(".pcbdoc") else eagle(p), indent=1))
