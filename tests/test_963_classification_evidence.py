"""A retry needs a DECISION on the record, not a process that made one (#963).

Run 29's combined loop never invoked `L3` (classify) or `L4` (re-enter) -- zero
times in 439 commands -- while `L5` PRINTED the `--stage L3` command in three of
its six emissions. The mechanical root is that CONTINUE returns
`<stage_instructions>`, and `main` derives the exit code from whether the text
starts with `<error>`, so the advice sat inside a success. Fifty-seven inline
routing calls then ran against an unclassified blocker, and the run recorded a
"geometrically unsatisfiable" stop that an outside reader refuted in one pass
(BLOCKING 2 -> 0) using a board the routing half had already written and the
ledger named zero times.

WHY THE GATE IS ON A ROW AND NOT ON A STAGE. #963's follow-up objects, rightly,
that requiring an `L3` invocation or a fresh prompt file would refuse a model
that diagnosed the failure inline or through another harness. So what is
required is the EVIDENCE: a `--kind classification --shape <...>` row, which any
topology can write, which changes no board, and which enters neither half's
plateau window -- so producing it cannot move a verdict, only make one
available. `test_the_refusal_asks_for_a_row_and_names_no_process` is the pin
that keeps it that way; a future editor restoring the stage command to the
refusal text is the likeliest way this becomes topology-bound again.

THREE CONJUNCTS, and every one of them is a way the gate would otherwise be
wrong rather than a belt-and-braces guard:

  * `blocking != 0`. L3 at `blocking == 0` returns "nothing to classify" and
    tells the reader not to bounce back, so a quality-polishing run CANNOT
    produce the row -- gating it would refuse such a run forever.
  * ROUTING laps only. A placement lap after `shape=placement` is the
    classification being ACTED ON.
  * "No classification row anywhere" is its own arm. "Laps since the last
    classification" is vacuously false when there has never been one -- which
    is precisely run 29 -- so a predicate without this arm cannot catch the
    case it was written for.

THE THRESHOLD IS TWO, and the first cut said one and called that derived. The
derivation stopped one sentence early. L4's parameter arm reads in full:

    Record it, then go back to L3 with the new score. If two parameter
    iterations in a row do not move `blocking`, the shape was probably not
    parameter -- re-measure rather than trying a third.

So L4 authorises the second lap explicitly and asks for a re-measurement before
the THIRD. A gate refusing the second put L3 and L4 in contradiction: the loop
refusing what its own re-entry stage had just told the run to do.

MEASURED COST, which the first cut did not measure at all: replayed over the 28
`wk/**/ledger.jsonl` in this WORKING TREE -- `wk/` is gitignored, so they are
run artifacts rather than fixtures and re-deriving this needs a tree that has
them -- the gate at ONE fires somewhere in
18 of them -- including all four most recent runs -- with peak unclassified
streaks of 31, 26, 24 and 16, and only 2 of the 28 hold a classification row at
all. At TWO it still fires on those streaks, which is the point; it stops
refusing the single retry L4 authorises.

The retry gate itself lived in loop_driver's L5 and left with it; the tests
that drove L3/L4/L5 went too. What stays is converge's half -- the
classification state, the row's own refusals, and the stop-4 gate on
`record --final` -- which does not depend on any driver.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

RUN_ALL_TIMEOUT = 600

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'tests'), os.path.join(ROOT, 'py_placer'),
           ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_utils                                               # noqa: E402
import converge as C                                           # noqa: E402

CV = os.path.join(ROOT, 'py_placer', 'converge.py')
BOARD = os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')


def _rows(*rows):
    return [dict(r, iteration=i) for i, r in enumerate(rows)]


def lap(half='routing', **over):
    r = {'kind': 'placement' if half == 'placement' else 'completion',
         'accepted': True, 'score': {'blocking': 2, 'quality': {}}}
    r.update(over)
    return r


def classification(shape='parameter', **over):
    r = {'kind': 'classification', 'accepted': True, 'shape': shape,
         'lever': 'the escape faces are saturated'}
    r.update(over)
    return r


def _cv(args):
    return subprocess.run([sys.executable, '-X', 'utf8', CV] + args,
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=ROOT)


def _argv(args):
    return [sys.executable, '-X', 'utf8', CV] + args


def _ledger(td, name, rows):
    p = os.path.join(td, name)
    with io.open(p, 'w', encoding='utf-8') as fh:
        for i, r in enumerate(rows):
            fh.write(json.dumps(dict(r, iteration=i)) + '\n')
    return p


def _score(td, name, blocking=2):
    p = os.path.join(td, name)
    with io.open(p, 'w', encoding='utf-8') as fh:
        json.dump({'blocking': blocking, 'quality': {}, 'ungraded': []}, fh)
    return p


def test_classification_state_counts_laps_since_the_decision():
    """And counts them with `_is_lap`, so the rows that turn no loop are out.

    #904 made that ONE predicate for a measured reason: three readers
    disagreed, and a freeze row silently retracted three recorded declarations.
    Counting here with a fresh kind-match would have been a fourth reader.
    """
    assert C._classification_state(_rows(lap(), lap())) is None, \
        'no classification row at all must be None, not an empty state'
    st = C._classification_state(_rows(lap(), classification(), lap(),
                                       lap('placement')))
    assert st['shape'] == 'parameter', st
    assert st['iteration'] == 1, st
    assert st['laps_since'] == {'routing': 1, 'placement': 1}, st

    # The three shapes that are NOT laps, in the window after the decision.
    st = C._classification_state(_rows(
        classification(),
        lap(final=True, stop_condition='STUCK'),
        lap(exhausted={'half': 'routing', 'reason': 'spent'}),
        {'kind': 'systemic', 'accepted': True, 'lever': 'a freeze'}))
    assert st['laps_since']['routing'] == 0, (
        'a close-out, a declaration and a freeze turn no loop: ' + str(st))

    # The LAST one wins, and its own shape is the one reported.
    st = C._classification_state(_rows(classification('parameter'), lap(),
                                       classification('floorplan')))
    assert (st['shape'], st['laps_since']['routing']) == ('floorplan', 0), st
    print("  PASS: the last decision, and the laps recorded after it")


def test_a_recorded_classification_moves_no_verdict():
    """Writing the row is genuinely free.

    `_HALF` has no `classification` key, so the row enters neither plateau
    window and the commensurability lookback skips it. If that stopped being
    true, a gate would be charging a run for satisfying it.
    """
    with tempfile.TemporaryDirectory() as td:
        rows = [lap()] * 3
        # The halves read exactly the same before and after the row.
        led_before = _ledger(td, 'b.jsonl', rows)
        led_after = _ledger(td, 'a.jsonl', rows + [classification()])
        sp = _score(td, 'v.json')
        before = json.loads(_cv(['verdict', '--ledger', led_before,
                                 '--score', sp]).stdout)
        after = json.loads(_cv(['verdict', '--ledger', led_after,
                                '--score', sp]).stdout)
        for half in ('placement', 'routing'):
            assert before[half] == after[half], (
                f'recording a classification moved the {half} half: '
                f'{before[half]} -> {after[half]}')
        assert before['verdict'] == after['verdict'], (before['verdict'],
                                                       after['verdict'])
    print("  PASS: the row moves neither half")


def test_a_classification_row_must_name_a_shape():
    """Otherwise the gate is a formality one flagless command clears."""
    with tempfile.TemporaryDirectory() as td:
        led = os.path.join(td, 'l.jsonl')
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD,
                   '--kind', 'classification', '--lever', 'a decision']),
            refuse='needs --shape', code=2)
        assert not os.path.exists(led), 'nothing may be written on refusal'
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'floorplan',
                    '--lever', 'a decision']).returncode == 0
    print("  PASS: a classification names the shape it decided")


def test_a_measured_unfixable_close_out_needs_a_live_classification():
    """Stop condition 4 is the claim run 29 recorded falsely.

    Bound to the row that MAKES the claim rather than to the stage that prints
    it: run 29's close-out was written without L5's advice carrying at all, so
    a gate in the driver would have been one more thing to walk past.
    """
    lenses = []
    with tempfile.TemporaryDirectory() as td:
        for name in ('connectivity', 'drc', 'spec'):
            p = os.path.join(td, f'verdict_{name}.txt')
            io.open(p, 'w', encoding='utf-8').write(
                f'VERDICT=PASS:lens={name}\n')
            lenses += ['--lens-file', p]
        led = os.path.join(td, 'l.jsonl')
        base = ['record', '--ledger', led, '--board', BOARD, '--final',
                '--kind', 'completion', '--stop-condition', '4'] + lenses
        run_utils.check(_argv(base),
                        refuse='no classification row was ever recorded',
                        code=2)

        # A PLATEAU is a different claim and needs none of this.
        assert _cv(['record', '--ledger', led, '--board', BOARD, '--final',
                    '--kind', 'completion', '--stop-condition', 'STUCK']
                   + lenses).returncode == 0, 'STUCK is not an unfixability claim'

        led2 = os.path.join(td, 'l2.jsonl')
        assert _cv(['record', '--ledger', led2, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'placement',
                    '--lever', 'no lane exists at the escape faces']
                   ).returncode == 0
        assert _cv(['record', '--ledger', led2, '--board', BOARD, '--final',
                    '--kind', 'completion', '--stop-condition', '4'] + lenses
                   ).returncode == 0, 'a classified 4 must be accepted'

        # ...and a routing lap AFTER the decision makes the claim stale again.
        assert _cv(['record', '--ledger', led2, '--board', BOARD,
                    '--kind', 'completion', '--lever', 'one more arm']
                   ).returncode == 0
        led3 = os.path.join(td, 'l3.jsonl')
        io.open(led3, 'w', encoding='utf-8').write(
            io.open(led2, encoding='utf-8').read())
        run_utils.check(
            _argv(['record', '--ledger', led3, '--board', BOARD, '--final',
                   '--kind', 'completion', '--stop-condition', '4'] + lenses),
            refuse='lap(s) were recorded after the last classification',
            code=2)
    print("  PASS: a measured-unfixable claim needs the measurement recorded")


def test_a_classification_row_must_name_its_measurement():
    """`--shape` alone left the gate clearable by a command recording nothing.

    Measured by a verifier on a reconstruction of run 29 (57 completion rows,
    blocking 2, no classification): stop-4 refused, one lever-less `record
    --kind classification --shape parameter` ran, stop-4 was then ACCEPTED.
    The same `cmd_record`, thirty lines earlier, refuses `--exhausted` without
    a non-empty reason for the same reason -- an unreasoned declaration is
    just a lower --flat with extra steps.
    """
    with tempfile.TemporaryDirectory() as td:
        led = os.path.join(td, 'l.jsonl')
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD,
                   '--kind', 'classification', '--shape', 'parameter']),
            refuse='needs --lever', code=2)
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD,
                   '--kind', 'classification', '--shape', 'parameter',
                   '--lever', '   ']),
            refuse='needs --lever', code=2)
        assert not os.path.exists(led), 'nothing may be written on refusal'
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'parameter',
                    '--lever', 'lane supply 2 short at the west face']
                   ).returncode == 0
    print("  PASS: a classification names the measurement that named it")


def test_a_rejected_classification_is_not_a_decision():
    """A decision that was thrown away is not one the next lap can act on."""
    st = C._classification_state(_rows(classification(accepted=False), lap()))
    assert st is None, ('a --rejected classification satisfied the gate: '
                        + str(st))
    st = C._classification_state(_rows(classification(), lap()))
    assert st is not None and st['laps_since']['routing'] == 1, st
    print("  PASS: a rejected classification is not the decision of record")


def test_a_measured_unfixable_claim_counts_laps_of_EITHER_half():
    """Unlike the retry gate, and for the opposite reason.

    "This board cannot be fixed" is a claim about the whole board, so a
    placement lap after the decision makes it as stale as a routing lap does.
    Measured before this: `classification(shape=placement)` plus six placement
    laps reached stop-4 untouched.
    """
    lenses = []
    with tempfile.TemporaryDirectory() as td:
        for name in ('connectivity', 'drc', 'spec'):
            p = os.path.join(td, f'verdict_{name}.txt')
            io.open(p, 'w', encoding='utf-8').write(
                f'VERDICT=PASS:lens={name}\n')
            lenses += ['--lens-file', p]
        led = os.path.join(td, 'l.jsonl')
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'placement',
                    '--lever', 'no lane exists at the escape faces']
                   ).returncode == 0
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'placement', '--lever', 'a placement lap']
                   ).returncode == 0
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD, '--final',
                   '--kind', 'completion', '--stop-condition', '4'] + lenses),
            refuse='1 placement, 0 routing', code=2)
    print("  PASS: a placement lap makes an unfixability claim stale too")


def test_a_ledger_line_that_is_not_an_object_is_not_a_traceback():
    """Both guards, on the path that actually walks the rows.

    A round-2 verifier mutated `isinstance(row, dict)` out of `_is_lap` AND
    out of `_classification_state` and neither died: the hardened `_is_lap` is
    UNREACHABLE from `record --final --stop-condition 4`, because
    `_classification_state` walks the same rows first and tracebacked before
    the laps were ever counted. A ledger is append-only text that several
    tools and a human can write to, so a bare string, a list or a null on one
    line is the ordinary damaged-file case -- and the gate this feeds is the
    one that refuses the loop's strongest claim. A traceback there is not a
    refusal, it is an argparse accident wearing a refusal's exit code.
    """
    bad = [{'kind': 'classification', 'accepted': True, 'shape': 'parameter',
            'lever': 'the escape faces are saturated'},
           'not an object at all', ['neither', 'is', 'this'], None,
           {'kind': 'completion', 'accepted': True,
            'score': {'blocking': 2, 'quality': {}}}]
    st = C._classification_state(bad)
    assert st is not None and st['laps_since']['routing'] == 1, (
        'the walk did not survive three non-object rows: ' + str(st))
    assert C._classification_rejected(bad) == 0, 'a string is not a row'
    with tempfile.TemporaryDirectory() as td:
        led = os.path.join(td, 'bad.jsonl')
        with io.open(led, 'w', encoding='utf-8') as fh:
            for r in bad:
                fh.write(json.dumps(r) + '\n')
        lenses = []
        for name in ('connectivity', 'drc', 'spec'):
            p = os.path.join(td, f'verdict_{name}.txt')
            io.open(p, 'w', encoding='utf-8').write(
                f'VERDICT=PASS:lens={name}\n')
            lenses += ['--lens-file', p]
        # It must REFUSE -- one routing lap after the decision -- and the
        # reason must be the lap count, not a NoneType/str attribute error.
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD, '--final',
                   '--kind', 'completion', '--stop-condition', '4'] + lenses),
            refuse='0 placement, 1 routing', code=2)
    print("  PASS: a damaged ledger line refuses for the right reason")


def test_a_ledger_of_only_rejected_classifications_says_so():
    """The refusal must not tell the reader a false thing about their file.

    With three `--rejected` classification rows on file it said "no
    classification row was ever recorded", which is untrue of the ledger the
    reader is looking at -- and the two cases need different actions: nobody
    classified (go classify) against every classification was thrown away
    (accept one, or say why none of them holds).
    """
    rows = _rows(classification(accepted=False),
                 classification(accepted=False, shape='placement'))
    assert C._classification_state(rows) is None
    assert C._classification_rejected(rows) == 2
    with tempfile.TemporaryDirectory() as td:
        led = _ledger(td, 'rej.jsonl', rows)
        lenses = []
        for name in ('connectivity', 'drc', 'spec'):
            p = os.path.join(td, f'verdict_{name}.txt')
            io.open(p, 'w', encoding='utf-8').write(
                f'VERDICT=PASS:lens={name}\n')
            lenses += ['--lens-file', p]
        run_utils.check(
            _argv(['record', '--ledger', led, '--board', BOARD, '--final',
                   '--kind', 'completion', '--stop-condition', '4'] + lenses),
            refuse='every one was --rejected', code=2)
    print("  PASS: rejected-only reads as rejected, not as never-written")


def test_the_lever_may_not_be_the_shape_word_again():
    """The null lever, in the one spelling the gate can actually detect.

    A verifier's F7: `--shape parameter --lever parameter` clears everything.
    It cannot be detected in general -- no gate reads a sentence and knows
    whether a measurement is behind it, and the sub-issue says exactly that --
    but the degenerate case, where the "measurement" is the shape word itself,
    is the same row as `--lever ""` with a word typed in it. Refusing more
    than that would refuse honest short levers, so this is deliberately the
    only spelling it catches, and the PR says so.
    """
    with tempfile.TemporaryDirectory() as td:
        led = os.path.join(td, 'l.jsonl')
        for word in ('parameter', ' Parameter.', 'placement'):
            r = _cv(['record', '--ledger', led, '--board', BOARD,
                     '--kind', 'classification', '--shape', 'parameter',
                     '--lever', word])
            assert r.returncode == 2, (
                f'--lever {word!r} was accepted as a measurement:\n'
                + (r.stdout + r.stderr)[-400:])
            assert 'names the shape again' in r.stderr, r.stderr[-400:]
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'parameter',
                    '--lever', 'parameter: the escape faces are saturated']
                   ).returncode == 0, 'an honest lever must still record'
    print("  PASS: a lever that only repeats the shape is not a measurement")



def test_the_one_case_where_recording_it_DOES_move_the_verdict():
    """"Side-effect free" is true of the plateau windows and of nothing else.

    A pre-push reviewer built a 99-row ledger at the default `--budget 100`:
    `verdict` said CONTINUE, the mandated remedy (`record --kind
    classification`) was run, and `verdict` then said BUDGET. The gate's own
    escape ended the run. It is not a defect -- a row is a row and the budget
    counts rows -- but four places said "moves no verdict" with no exception,
    and the one place it does move it is the place the reader has just been
    sent to. This pins the mechanism so the sentence cannot drift back.
    """
    with tempfile.TemporaryDirectory() as td:
        rows = [lap() for _ in range(99)]
        led = _ledger(td, 'budget.jsonl', rows)
        sc = _score(td, 'sc.json')

        def verdict():
            r = _cv(['verdict', '--ledger', led, '--score', sc,
                     '--budget', '100'])
            # CONTINUE is exit 4 here and BUDGET is 3 -- the codes are the
            # verdict, so this asserts only that the doc parsed.
            assert r.stdout.strip().startswith('{'), r.stderr[-300:]
            return json.loads(r.stdout)['verdict']

        assert verdict() == 'CONTINUE', 'the fixture starts under budget'
        assert _cv(['record', '--ledger', led, '--board', BOARD,
                    '--kind', 'classification', '--shape', 'parameter',
                    '--lever', 'the escape faces are saturated']
                   ).returncode == 0
        assert verdict() == 'BUDGET', (
            'the 100th row did not end the run, so this test no longer '
            'describes the boundary it was written for')
        # ...and the plateau claim, which IS true, still holds: the row is in
        # neither window.
        doc = json.loads(_cv(['verdict', '--ledger', led, '--score', sc,
                              '--budget', '400']).stdout)
        assert doc['classification'] is not None
        for half in ('placement', 'routing'):
            assert 'classification' not in str(doc[half].get('why') or ''), \
                doc[half]
    print("  PASS: the row is outside both plateau windows and inside the "
          "budget")


if __name__ == '__main__':
    run_utils.evidence(BOARD)
    for k, v in sorted(globals().items()):
        if k.startswith('test_'):
            print("--- " + k)
            v()
    print("ALL PASS")
