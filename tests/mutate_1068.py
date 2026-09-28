#!/usr/bin/env python3
"""The #1068 mutation battery: the re-seat's `intent` basis and the tether
terms `IntentProbe` measures.

`tests/test_reseat_intent_basis_parity.py` pins that the probe counts the
tether rules the way the grade does, once per claim, locked claims included,
and that the re-seat is accepted on them; `tests/test_698_reseat_acceptance.py`
arm H pins that measuring them never arms the quench's tether gate. Each row
is a plausible regression of one of those; each must be KILLED.

NOT named `test_*.py`, so `tests/run_all.py` does not collect it: it REWRITES
the engine in place. One writer per tree. It refuses to start on a dirty
engine.

    python3 tests/mutate_1068.py
    python3 tests/mutate_1068.py --row the-reseat-probe-gets-no-tethers
    python3 tests/mutate_1068.py --list

A row is KILLED by a FAILURE **or an ERROR**. An anchor that does not match
EXACTLY ONCE is reported as BROKEN rather than skipped. Python `str.replace`,
never `sed`.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS)

SEEDER = os.path.join(_ROOT, 'py_placer', 'placement', 'seeder.py')
QUENCH = os.path.join(_ROOT, 'py_placer', 'placement', 'quench.py')
PLACE_SEED = os.path.join(_ROOT, 'py_placer', 'place_seed.py')
TARGETS = {'s': SEEDER, 'q': QUENCH, 'p': PLACE_SEED}

TPAR = os.path.join(_TESTS, 'test_reseat_intent_basis_parity.py')
T698 = os.path.join(_TESTS, 'test_698_reseat_acceptance.py')

ROWS = [
    # The re-seat builds its probe from the zones only again: the pre-#1068
    # behaviour, `intent 0->0` beside a decap GRADE ERROR.
    ('the-reseat-probe-gets-no-tethers', 's',
     "        probe = _q.IntentProbe(state, zones=_bundle['zones'],\n"
     "                               tethers=_bundle.get('tethers'))\n",
     "        probe = _q.IntentProbe(state, zones=_bundle['zones'],\n"
     "                               tethers=None)\n",
     (TPAR,), 'KILLED'),

    # A tether term counted once per REF it binds: a cap on a rail with two
    # chips counts three times.
    ('a-tether-counted-per-ref', 'q',
     "            if v > t.threshold + legality.EPS:\n"
     "                count += 1\n",
     "            if v > t.threshold + legality.EPS:\n"
     "                count += len(set(t.refs))\n",
     (TPAR,), 'KILLED'),

    # The probe drops a claim whose refs are all locked, as the GATE does;
    # the grade still counts it.
    ('the-probe-drops-locked-claims-like-the-gate', 'q',
     "            t for t in (state.tether_terms_for(tethers, keep_locked=True)\n",
     "            t for t in (state.tether_terms_for(tethers, keep_locked=False)\n",
     (TPAR,), 'KILLED'),

    # Measuring the probe ARMS the quench's tether gate on the seat state.
    ('the-probe-arms-the-tether-gate', 'q',
     "            if want & set(t.refs))\n"
     "        self._tethers_of: Dict[str, Tuple[int, ...]] = {}\n",
     "            if want & set(t.refs))\n"
     "        state._tether_terms = list(self.tethers)\n"
     "        self._tethers_of: Dict[str, Tuple[int, ...]] = {}\n",
     (T698,), 'KILLED'),

    # The per-ref vector prune samples omits the tether terms: prune reverts
    # a seat made for a decap reason as a pure hpwl loss.
    ('prune-sees-no-tether-terms', 'q',
     "        idx = self._tethers_of.get(ref, ())\n"
     "        if idx:\n",
     "        idx = ()\n"
     "        if idx:\n",
     (TPAR,), 'KILLED'),

    # The printed basis goes back to a bare `intent`.
    ('the-printed-basis-is-unlabelled', 'p',
     "                return f\"intent[{_ir}]\" if term == 'intent' else term\n",
     "                return term\n",
     (TPAR,), 'KILLED'),
]

# Every anchor must match its target exactly once BEFORE anything is
# rewritten. A stale anchor otherwise reports BROKEN mid-run, after the
# witnesses have been paid for; this is the one second (#877).
from mutation_anchors import preflight   # noqa: E402
preflight(__file__)


def _git_clean(paths):
    r = subprocess.run(['git', 'diff', '--quiet', '--'] + list(paths),
                       cwd=_ROOT)
    return r.returncode == 0


def _run(tests):
    for t in tests:
        r = subprocess.run([sys.executable, '-X', 'utf8', t],
                           cwd=_ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            return True, f"{os.path.basename(t)} exit {r.returncode}"
    return False, "all named tests passed"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--row', action='append', default=None)
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()

    if a.list:
        for name, tgt, _o, _n, tests, exp in ROWS:
            print(f"  {exp:9} {name}  [{tgt}] "
                  f"-> {', '.join(os.path.basename(t) for t in tests)}")
        return 0

    rows = ROWS
    if a.row:
        unknown = [n for n in a.row if n not in {r[0] for r in ROWS}]
        if unknown:
            print(f"no such row: {', '.join(unknown)}; try --list",
                  file=sys.stderr)
            return 2
        rows = [r for r in ROWS if r[0] in set(a.row)]

    if not _git_clean(TARGETS.values()):
        print("REFUSED: the engine files are dirty. Restoring would write the "
              "COMMITTED text back over uncommitted work.", file=sys.stderr)
        return 2

    originals = {k: io.open(p, encoding='utf-8').read()
                 for k, p in TARGETS.items()}
    verdicts = []
    try:
        for name, tgt, old, new, tests, expect in rows:
            src = originals[tgt]
            n = src.count(old)
            if n != 1:
                verdicts.append((name, 'BROKEN', f"anchor matched {n} times"))
                print(f"  BROKEN   {name} -- anchor matched {n} times")
                continue
            io.open(TARGETS[tgt], 'w', encoding='utf-8', newline='').write(
                src.replace(old, new, 1))
            killed, why = _run(tests)
            io.open(TARGETS[tgt], 'w', encoding='utf-8',
                    newline='').write(src)
            got = 'KILLED' if killed else 'SURVIVED'
            mark = 'ok' if got == expect else 'WRONG'
            verdicts.append((name, got, why))
            print(f"  {got:9}{'' if mark == 'ok' else ' WRONG'} {name} -- {why}")
    finally:
        for k, p in TARGETS.items():
            io.open(p, 'w', encoding='utf-8', newline='').write(originals[k])

    wrong = [v for v, (name, got, _w) in zip(rows, verdicts)
             if got != v[5]]
    broken = [n for n, g, _w in verdicts if g == 'BROKEN']
    print(f"\n{len(verdicts)} row(s): "
          f"{sum(1 for _n, g, _w in verdicts if g == 'KILLED')} killed, "
          f"{sum(1 for _n, g, _w in verdicts if g == 'SURVIVED')} survived, "
          f"{len(broken)} broken, {len(wrong)} disagreeing with expectation")
    return 1 if (wrong or broken) else 0


if __name__ == '__main__':
    sys.exit(main())
