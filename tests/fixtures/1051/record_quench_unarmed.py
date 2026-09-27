#!/usr/bin/env python3
"""Record (or re-run) the #1051 phase-4 bit-identity cases: the quench on an
intent that declares no array, no `rigid` block and no tether limit.

Run from a checkout's root. It builds the gate through
`floorplan.resolve_intent_gate`, whatever keys that tree's bundle carries, so
the SAME script runs on the pre-phase-4 tree (8bcce3fba, where
`quench_unarmed_baseline.json` was recorded) and on this one, and
`tests/test_1051_quench_blocks.py` compares the two.

    python3 tests/fixtures/1051/record_quench_unarmed.py > out.json
"""
import json
import os
import sys

ROOT = os.getcwd()
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, ROOT)

#: (board, --group-by sources for the caller's groups, a keep-out?, quench
#: kwargs). Two boards; the second also carries caller groups, so the plain
#: filter of the group phase is on the record, and a declared keep-out over
#: the board's centre, so the #702 gate is ACTIVE -- the conjunct order in
#: `candidate_valid` and the swap guard are then on the record too, not just
#: a gate that binds nothing.
CASES = [
    ('kicad_files/splitflap_driver.kicad_pcb', (), False,
     {'max_passes': 2}),
    ('kicad_files/esp_prog.kicad_pcb', ('sheet',), True,
     {'max_passes': 2}),
]


def _round(v):
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, dict):
        return {str(k): _round(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    return v


def run_case(board, sources, keepout, kw):
    from kicad_parser import parse_kicad_pcb
    from placement import floorplan
    from placement.groups import derive_groups
    from placement.quench import quench
    path = os.path.join(ROOT, board)
    pcb = parse_kicad_pcb(path)
    doc = floorplan.emit_intent(pcb, path)
    if keepout:
        x0, y0, x1, y1 = pcb.board_info.board_bounds
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        doc['keepouts'] = [{'name': 'centre', 'rect': [cx - 3.0, cy - 3.0,
                                                       cx + 3.0, cy + 3.0]}]
    intent = floorplan.intent_from_dict(doc)
    gate, _p = floorplan.resolve_intent_gate(intent, pcb, ('kicad', 'sheet'))
    groups = derive_groups(pcb, sources) if sources else None
    m = {}
    placements = quench(pcb, path, clearance=0.2, board_edge_clearance=0.5,
                        metrics_out=m, intent_gate=gate, groups=groups, **kw)
    return {'board': board,
            'placements': _round(sorted(
                [p['reference'], p['new_x'], p['new_y'], p['new_rotation']]
                for p in placements)),
            'metrics': _round(m)}


def main():
    import io
    from contextlib import redirect_stdout
    # Everything the engine prints goes to a sink: stdout carries the JSON
    # and nothing else.
    with redirect_stdout(io.StringIO()):
        out = [run_case(b, s, k, kw) for b, s, k, kw in CASES]
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
