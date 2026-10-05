"""The obstacle builders price a net with the same soft-cost sources everywhere.

Rows:
  - a net is not priced against its OWN track-proximity entry (a multipoint
    net's Phase 3 taps were pushed off its own main route), nor its river
    siblings', and nothing is copied when nothing is dropped; the same view
    is handed out again while its sources are unchanged (the merge memo is
    keyed on its identity) and a new one once any of them changes;
  - stub-proximity sources: every unrouted net, a multipoint net whose taps
    are still pending although its Phase 1 route is in, and a pre-existing net
    ripped this run and not yet back; never the net being routed, never a
    routed net with nothing pending;
  - Phase 3's fast builder takes the ripped-route ghost ledgers, and every
    Phase 3 call hands them over (it routed blind to pending victims'
    corridors, and differently whether length matching sent it to the slow
    builder or not);
  - the diff-pair layer-swap fallback builds every map with the main loop's
    builder (its victim-reroute map omitted the still-unrouted nets' copper
    and the pair's own same-net rings).

    python3 tests/test_builder_cost_sources.py
"""
import inspect
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

import routing_context as rc  # noqa: E402


def test_own_track_proximity_entry_dropped():
    cache = {5: 'own', 6: 'other', 7: 'sibling', -1: 'bga'}
    got = rc._per_net_cost_sources(cache, (5,), sibs={7})
    assert set(got) == {6, -1}, got
    assert rc._per_net_cost_sources(cache, (9,)) is cache, "copied for nothing"
    assert set(rc._per_net_cost_sources(cache, (5, 6))) == {7, -1}
    again = rc._per_net_cost_sources(cache, (5,), sibs={7})
    assert again is got, "an unchanged view was rebuilt: the merge memo misses"
    cache[6] = 'rerouted'
    fresh = rc._per_net_cost_sources(cache, (5,), sibs={7})
    assert fresh is not got and fresh[6] == 'rerouted', fresh


def test_stub_proximity_sources():
    config = types.SimpleNamespace(_pending_multipoint={3: object()})
    pcb = types.SimpleNamespace(_preexisting_rips={8: 'OLD'})
    ids = rc._stub_proximity_source_ids(
        config, pcb, all_unrouted_net_ids=[1, 2, 3, 4],
        routed_net_ids=[2, 3], exclude={1})
    # 1 is being routed; 2 is routed and done; 3 is routed with taps pending;
    # 4 is unrouted; 8 is a ripped pre-existing net not in the batch list.
    assert ids == [3, 4, 8], ids
    bare = rc._stub_proximity_source_ids(
        types.SimpleNamespace(), types.SimpleNamespace(), [1, 2, 3], [2], {1})
    assert bare == [3], "without pending/rips it is the old rule"


def test_phase3_builder_takes_the_ghosts():
    params = inspect.signature(rc.build_incremental_obstacles).parameters
    assert 'ripped_route_layer_costs' in params
    assert 'ripped_route_via_positions' in params
    import phase3_routing
    src = inspect.getsource(phase3_routing)
    calls = [m.start() for m in re.finditer(r'build_incremental_obstacles\(', src)]
    calls = [c for c in calls if not src[max(0, c - 40):c].rstrip().endswith('import')]
    assert len(calls) >= 7, len(calls)
    for c in calls:
        call = src[c:src.index(')', c + src[c:].index('cache') + 5) + 1]
        call = src[c:c + len(call) + 300]           # the call and its tail
        assert 'ripped_route_via_positions' in call, src[c:c + 300]


def test_fallback_maps_use_the_shared_builder():
    import layer_swap_fallback
    src = inspect.getsource(layer_swap_fallback.try_fallback_layer_swap)
    assert 'clone_fresh()' not in src, "a hand-built map is back"
    assert src.count('_pair_map(') >= 4, src.count('_pair_map(')   # def + 3 uses
    import diff_pair_loop
    import reroute_loop
    for mod in (diff_pair_loop, reroute_loop):
        msrc = inspect.getsource(mod)
        i = msrc.index('try_fallback_layer_swap(')
        assert 'ripped_route_via_positions=state.ripped_route_via_positions' in \
            msrc[i:i + 2000], mod.__name__


TESTS = [test_own_track_proximity_entry_dropped, test_stub_proximity_sources,
         test_phase3_builder_takes_the_ghosts,
         test_fallback_maps_use_the_shared_builder]


if __name__ == '__main__':
    fails = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL {t.__name__}: {e}")
    print('ALL PASS' if not fails else f'{fails} FAILED')
    sys.exit(1 if fails else 0)
