#!/usr/bin/env python3
"""#1051 phases 3-4: the seeder and the quench give the SAME answer in every
process, whatever PYTHONHASHSEED is.

Python randomises string hashing per process, so iterating a `set` of refs --
or sorting one by a key two refs can tie on -- yields a different order in
each process. Found by a re-run: `test_1051_seed_arrays`'s anchor-rounds arm
started from gate 993.513 on one run and 1029.559 on another. The cause was
the `--anchors-first` queue (and the anchor rounds' re-seat order), sorted
over the SET `unplaced` by extent alone: identical footprints tie, and the
tie resolved in hash order (seeder.py since 5070430d3, before this branch).

Each case runs in two subprocesses with PYTHONHASHSEED 1 and 2 and compares
every placement and the metrics:

* seed + polish (`place_seed --anchors-first --anchor-rounds 3`) on watchy,
  with the detector's rows and decap limits declared -- the path that
  diverged;
* quench only on splitflap, with rigid rows and tethers armed.

    python3 tests/test_1051_determinism.py
"""
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RUN_ALL_TIMEOUT = 1200
SEEDS = ('1', '2')


def _paths():
    for d in ('py_router', 'py_placer', 'py_tools'):
        sys.path.insert(0, os.path.join(ROOT, d))
    sys.path.insert(0, ROOT)


def _intent(board, td):
    from kicad_parser import parse_kicad_pcb
    from placement import floorplan as fp
    doc = fp.emit_intent(parse_kicad_pcb(board), board, derive_arrays='auto')
    assert doc['arrays'], "no rows derived: the case would not arm them"
    doc['decaps'] = dict(doc.get('decaps') or {}, max_distance_mm=3.0,
                         max_pin_distance_mm=3.0)
    path = os.path.join(td, 'intent.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    return path


def _worker(case):
    """Runs in the subprocess; prints one JSON line."""
    _paths()
    from kicad_parser import parse_kicad_pcb
    from placement import floorplan as fp
    td = tempfile.mkdtemp()
    if case == 'seed':
        from placement import seeder
        board = os.path.join(ROOT, 'kicad_files', 'watchy.kicad_pcb')
        with redirect_stdout(io.StringIO()):
            it = fp.load_intent(_intent(board, td))
            pcb = parse_kicad_pcb(board)
            res = seeder.seed_from_intent(
                pcb, board, it, random.Random('1'),
                group_sources=('kicad', 'sheet'), clearance=0.2,
                anchors_first=True, anchor_rounds=3)
        out = {'placements': sorted(
                   [p['reference'], round(p['new_x'], 6),
                    round(p['new_y'], 6), round(p['new_rotation'], 6)]
                   for p in res['placements']),
               'notes': [n for n in res['notes']
                         if n.startswith('anchor')],
               'arrays_formed': sorted(res['arrays_formed'])}
        # The polish, on the written seed, through the CLI's own path.
        from placement.writer import write_placed_output
        from placement.portfolio import copy_siblings
        seeded = os.path.join(td, 'seed.kicad_pcb')
        with redirect_stdout(io.StringIO()):
            write_placed_output(board, seeded, res['placements'])
        copy_siblings(board, seeded)
        case = ('quench', seeded, it)
    else:
        board = os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')
        with redirect_stdout(io.StringIO()):
            it = fp.load_intent(_intent(board, td))
        out = {}
        case = ('quench', board, it)
    from placement import quench as q
    _k, board, it = case
    pcb = parse_kicad_pcb(board)
    gate, _p = fp.resolve_intent_gate(it, pcb, ('kicad', 'sheet'))
    assert gate['rigid_blocks'] and gate['tethers'], gate
    m = {}
    with redirect_stdout(io.StringIO()):
        pl = q.quench(pcb, board, clearance=0.2, board_edge_clearance=0.5,
                      max_displacement=3.0, crossing_penalty=30.0,
                      length_weight=0.3, halo_coef=0.15, metrics_out=m,
                      intent_gate=gate, max_passes=4)
    out['quench'] = sorted([p['reference'], round(p['new_x'], 6),
                            round(p['new_y'], 6), round(p['new_rotation'], 6)]
                           for p in pl)
    out['metrics'] = json.loads(json.dumps(m, sort_keys=True, default=str))
    print(json.dumps(out, sort_keys=True))


def _run(case, hashseed):
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.abspath(__file__),
                        '--worker', case], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=ROOT, env=env,
                       timeout=1100)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _digest(o):
    return hashlib.md5(json.dumps(o, sort_keys=True).encode()).hexdigest()[:10]


def _same(case):
    a, b = (_run(case, s) for s in SEEDS)
    for key in sorted(set(a) | set(b)):
        assert a.get(key) == b.get(key), (
            f"{case}: `{key}` differs between PYTHONHASHSEED "
            f"{SEEDS[0]} and {SEEDS[1]}: {_digest(a.get(key))} vs "
            f"{_digest(b.get(key))}")
    return a


def test_seed_and_polish_are_hash_seed_independent():
    a = _same('seed')
    assert a['placements'] and a['quench'], "nothing placed or polished"
    assert any('anchor round' in n for n in a['notes']), a['notes']
    assert a['metrics'].get('rigid', {}).get('groups'), "no rigid group"
    print(f"  PASS: watchy seed ({len(a['placements'])} placements, "
          f"{len(a['arrays_formed'])} rows, anchor rounds) and its polish "
          f"({len(a['quench'])} moves, {len(a['metrics']['rigid']['groups'])}"
          f" rigid groups, tethers {sorted(a['metrics']['tethers']['terms'])})"
          f" identical under PYTHONHASHSEED {' and '.join(SEEDS)}")


def test_quench_with_rows_and_tethers_is_hash_seed_independent():
    a = _same('quench')
    assert a['quench'], "the quench moved nothing"
    print(f"  PASS: splitflap quench ({len(a['quench'])} moves, "
          f"{len(a['metrics']['rigid']['groups'])} rigid groups, "
          f"{a['metrics']['intent_gate']['rejected']} refusals) identical "
          f"under PYTHONHASHSEED {' and '.join(SEEDS)}")


TESTS = [
    test_seed_and_polish_are_hash_seed_independent,
    test_quench_with_rows_and_tethers_is_hash_seed_independent,
]


if __name__ == '__main__':
    if sys.argv[1:2] == ['--worker']:
        _worker(sys.argv[2])
        sys.exit(0)
    only = sys.argv[1:]
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
