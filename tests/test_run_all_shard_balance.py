"""run_all's shards balance on measured test durations.

A fan-out's wall-clock is its slowest shard. The strided split (every N-th
file by name) measured 2462 s on one shard against a 195 s mean over 50, since
test cost is nothing like uniform. With tests/run_all_durations.json present,
`run_all.shard` packs longest-first onto the least-loaded shard instead.

Rows:
  - for any shard count (more shards than tests included) the slices are
    disjoint and their union is every test, with or without a table;
  - with a table the slowest shard is no slower than the strided split's,
    and strictly faster on a skewed suite;
  - a test the table does not know is priced at the median of the known;
  - without a table the split is exactly the old strided one;
  - the committed table, when there is one, parses into seconds.

    python3 tests/test_run_all_shard_balance.py
"""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)

import run_all  # noqa: E402

NAMES = [f'test_{i:03d}.py' for i in range(40)]
PATHS = [os.path.join('nowhere', n) for n in NAMES]     # classified as unit
# Skewed like the real suite: a few very slow files, many quick ones, and the
# slow ones adjacent by name (a family), which is what striding lands badly.
COST = {n: (900.0 if i in (0, 1, 2, 3) else 60.0 if i < 10 else 5.0)
        for i, n in enumerate(NAMES)}


def _slices(count, durations):
    return [run_all.shard(PATHS, i, count, durations) for i in range(count)]


def _wall(slices, cost):
    return max(sum(cost[os.path.basename(p)] for p in s) for s in slices)


def test_slices_cover_exactly_once():
    for durations in (None, COST):
        for count in (1, 3, 7, 40, 55):
            slices = _slices(count, durations)
            flat = [p for s in slices for p in s]
            assert sorted(flat) == sorted(PATHS), (count, durations is None)
            assert len(flat) == len(set(flat)), count


def test_balanced_beats_strided():
    for count in (2, 4, 8):
        strided = _wall(_slices(count, None), COST)
        balanced = _wall(_slices(count, COST), COST)
        assert balanced <= strided, (count, balanced, strided)
    assert _wall(_slices(4, COST), COST) < _wall(_slices(4, None), COST)


def test_unknown_tests_get_the_median():
    partial = {n: c for n, c in COST.items() if n != NAMES[39]}
    a = _slices(4, partial)
    assert sorted(p for s in a for p in s) == sorted(PATHS)
    # The median of the known costs is 5 s, so the unknown file lands like a
    # cheap one -- never as a phantom 0 s test piled onto an already-full shard.
    loads = [sum(partial.get(os.path.basename(p), 5.0) for p in s) for s in a]
    assert max(loads) - min(loads) <= 900.0, loads


def test_no_table_is_the_strided_split():
    for count in (3, 50):
        for i in range(count):
            assert run_all.shard(PATHS, i, count, None) == PATHS[i::count]
            assert run_all.shard(PATHS, i, count, {}) == PATHS[i::count]


def test_committed_table_parses():
    table = run_all.load_durations()
    if not table:
        print('    (no committed table yet -- the strided split is in use)')
        return
    assert all(isinstance(v, float) and v >= 0 for v in table.values())
    assert all(k.startswith('test_') and k.endswith('.py') for k in table)


TESTS_LIST = [test_slices_cover_exactly_once, test_balanced_beats_strided,
              test_unknown_tests_get_the_median, test_no_table_is_the_strided_split,
              test_committed_table_parses]


if __name__ == '__main__':
    fails = 0
    for t in TESTS_LIST:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL {t.__name__}: {e}")
    print('ALL PASS' if not fails else f'{fails} FAILED')
    sys.exit(1 if fails else 0)
