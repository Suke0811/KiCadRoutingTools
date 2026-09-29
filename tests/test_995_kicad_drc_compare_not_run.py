#!/usr/bin/env python3
"""kicad_drc_compare exits 2 when a board was not compared (#995).

Without kicad-cli every board SKIPs. The CLI used to print "0 boards compared"
and exit 0, so a caller reading the exit code took a comparison that never ran
for agreement between KiCad and check_drc. Exit codes now:

  0  every board compared and consistent
  1  a board diverged
  2  a board was NOT compared, or none was given -- outranks 1

The first check drives the REAL skip path: the module's kicad-cli is pointed at
a path that does not exist, so kicad_items_for refuses before running anything
and no KiCad is needed. The precedence checks replace compare_board, so they
need none either.

    python3 tests/test_995_kicad_drc_compare_not_run.py
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, 'tests', 'stress'), os.path.join(ROOT, 'py_router')):
    if p not in sys.path:
        sys.path.insert(0, p)

import kicad_drc_compare as kdc

FAILS = []
BOARD = os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))


def _main(argv):
    saved = sys.argv
    sys.argv = ['kicad_drc_compare.py'] + list(argv)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = kdc.main()
    finally:
        sys.argv = saved
    return code, out.getvalue()


def t_no_kicad_cli_is_not_run():
    check('the fixture board exists', os.path.isfile(BOARD), BOARD)
    saved = kdc.KICAD_CLI
    kdc.KICAD_CLI = os.path.join(ROOT, 'no-such-dir', 'kicad-cli-995')
    try:
        code, out = _main([BOARD])
    finally:
        kdc.KICAD_CLI = saved
    check('the board SKIPs because kicad-cli is missing',
          'SKIP (kicad-cli not found' in out, out.strip().splitlines()[:1])
    check('missing kicad-cli exits 2, not 0', code == 2, f'exit {code}')
    check('it says NOT RUN and names the board',
          'NOT RUN: 1 of 1 board(s) not compared: splitflap_driver.kicad_pcb' in out,
          [ln for ln in out.splitlines() if 'NOT RUN' in ln])


def t_no_board_given_is_not_run():
    code, out = _main([])
    check('no board given exits 2', code == 2, f'exit {code}')
    check('it says no board was given', '(no board given)' in out)


def _row(kicad_only=0, checkdrc_only=0):
    return {'kicad_only': kicad_only, 'checkdrc_only': checkdrc_only,
            'kicad_connection_width': None}


def t_exit_precedence():
    saved = kdc.compare_board
    try:
        for label, results, want in (
                ('all consistent', [_row(), _row()], 0),
                ('one diverged', [_row(), _row(kicad_only=1)], 1),
                ('one not compared', [_row(), None], 2),
                ('diverged and not compared', [_row(checkdrc_only=2), None], 2)):
            it = iter(results)
            kdc.compare_board = lambda *a, **k: next(it)
            code, _ = _main(['a.kicad_pcb', 'b.kicad_pcb'])
            check(f'{label} exits {want}', code == want, f'exit {code}')
    finally:
        kdc.compare_board = saved


def main():
    t_no_kicad_cli_is_not_run()
    t_no_board_given_is_not_run()
    t_exit_precedence()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
