# #1051 evidence: glasgow from scratch, three arms, against the human layout

Produced by `tests/fixtures/1051/glasgow_three_arm.py`. Only the per-arm/seed
JSON results are committed. The boards are regenerable and are not
(`place_seed` is deterministic per seed).

## What was run

- **Input:** run 32's `wk/run32/glasgow_unplaced.kicad_pcb`, staged with
  `copy_board.py`.
- **Intent:** run 32's intent, `tests/fixtures/1051/glasgow_run32.intent.json`.
  It declares `decaps.max_distance_mm` 2.5, so stage 2.4 is armed in every arm.
- **Seeding:** `place_seed --clearance 0.2 --force`, polish ON, seeds 0-4.
- **Grading:** every arm is graded under the base intent as the common ruler.

| arm | what differs |
|---|---|
| a | nothing: the current seeder |
| b | every `check_floorplan --suggest-arrays` row declared as `arrays[]` (20 rows, accepted wholesale), then seed + quench |
| c | "the AI places the key parts": U30, RN1-RN12 and the 17 SN74LVC1T45 buffers written at their **human** pose (`kicad_files/glasgow_revC.kicad_pcb`) and stamped `(locked yes)`, then the rest seeded |
| cf | the same 30 poses declared as intent `fixed_poses[]` instead (seed 0 only; see findings) |

The detector suggests none of the RN banks and none of the buffer banks on this
board. It declines the two buffer banks and RN5/6 and RN11/12 as "bridges".
Arm c is therefore the only arm where those parts are placed as the human did.

**Commits.** Each JSON records the commit it ran at:
- arms a, b and cf: `0a2a3358e`;
- arm c, the four full routes and `setup.json`: `43eae2deb`.

`git diff 0a2a3358e 43eae2deb -- py_placer py_router py_tools` is empty, so
the engine was the same for all of them. The later commits touch only tests
and fixtures.

## Commands

```bash
export MSYS2_ARG_CONV_EXCL='*'   # not needed by the script; harmless
SRC=C:/Users/rob/Documents/prive/git/KiCadRoutingTools/wk/run32/glasgow_unplaced.kicad_pcb
# seeds, one process per arm (each ~15-30 min per seed on 8 cores under load)
for arm in a b c; do
  python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --src $SRC \
      --workdir W_$arm --arms $arm --probe-seeds &
done; wait
# probes (routes 202 nets on each board; ~1-3 h per board under load)
for s in 0 1 2; do
  python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --src $SRC \
      --workdir P_$s --arms a b c --seeds $s --probe-seeds $s \
      --reuse W_a W_b W_c &
done; wait
# full-board routes of the best seed of each arm (run 32's chain)
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --route a:4 --reuse W_a --workdir R_a4
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --route b:0 --reuse W_b --workdir R_b0
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --route c:1 --reuse W_c --workdir R_c1
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --route a:0 --reuse W_a --workdir R_a0
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --regrade-route a:0 a:4 b:0 c:1 --reuse R_a0 R_a4 R_b0 R_c1
# arm cf (fixed_poses), seed 0
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --src $SRC --workdir W_cf --arms cf --seeds 0 --probe-seeds
# the table, from the committed JSONs
python -X utf8 tests/fixtures/1051/glasgow_three_arm.py --table
```

## Results

### The routed outcome

**Probe.** `tests/test_placement_probe.py` routes the same 202 nets on both
boards at `--clearance 0.2`. The 202 nets are every net of fanout <= 20 on the
30 key parts or on a detector-row member, fixed off the unplaced board. The
ladder is failed nets / open nets / unconnected pad pairs / vias, OFF (arm a)
-> ON, same seed. Seeds 0-2 only: each board route took 1.5-3 h here.

| seed | a -> b | a -> c |
|---|---|---|
| 0 | 39 -> 34 / 2 -> 0 / 43 -> 29 / 479 -> 437, **better** | 39 -> **15** / 2 -> 0 / 43 -> 15 / 479 -> 413, **better** |
| 1 | 36 -> 45 / 0 -> 2 / 31 -> 37 / 443 -> 445, **worse** | 36 -> **14** / 0 -> 1 / 31 -> 11 / 443 -> 408, **better** |
| 2 | 29 -> 28 / 0 -> 0 / 22 -> 18 / 453 -> 484, better by 1 net | 29 -> **21** / 0 -> 1 / 22 -> 16 / 453 -> 391, **better** |
| sum of failed nets | 104 -> 107 | 104 -> 50 |

**Full-board route.** Run 32's chain was run on the best seed of each arm by
crossings, and graded with `check_drc` at the floor the chain wrote (0.1) plus
`check_connected`. There is ONE route per arm. CLAUDE.md measures a single
replay pair of a plane/oracle chain at 1-3 DRC and 8-14 connectivity issues
apart on identical code. Read these as a sanity check that agrees with the
probe, not as a second measurement.

| board | DRC | unrouted | broken | wall |
|---|---|---|---|---|
| a seed 4 (best a) | 8 (pad-via) | 0 | 20 | 8319 s |
| a seed 0 (extra) | 14 (pad-via) | 3 | 37 | 8146 s |
| b seed 0 (best b) | 4 (pad-via) | 1 | 25 | 8933 s |
| c seed 1 (best c) | 7 (pad-via) | 0 | **11** | 5437 s |

### Placement proxies

Measured by `render_placement` at clearance 0.2 with no ignored nets. The
human board measures 1352 crossings and 3641 mm hpwl.

| arm | crossings (mean +- sd, n=5) | x human | hpwl | x human |
|---|---|---|---|---|
| a | 3446 +- 216 | 2.55 | 5177 +- 121 | 1.42 |
| b | 3554 +- 291 | 2.63 | 5031 +- 218 | 1.38 |
| c | 2318 +- 88 | 1.71 | 4482 +- 54 | 1.23 |
| cf (seed 0) | 5989 | 4.43 | 8539 | 2.35 |

**Legality.**
- Every seed of every arm exits `place_seed` 4, with a non-empty grade under
  its own intent.
- Every seed carries one `legality` error under the base intent (cf: 2).
- The rest of the errors are decap tethers (`decap_distance`,
  `decap_pin_distance`) and `pins_to_edge`.
- Per seed, the error counts under the base intent are: a 9, 8, 13, 15, 16;
  b 12, 15, 19, 20, 15; c 19, 5, 22, 15, 11.
- No seed of a, b or c leaves a part unseated.
- In arm b, all 20 rows form on every seed. 2-9 members per seed are released
  by the polish (`rigid_released`).

## Findings, plainly

1. **(b), the detector's rows declared, does NOT route better than (a).**
   - The probe sum is 104 -> 107 failed nets: better on seeds 0 and 2, worse
     on seed 1.
   - Crossings are no better either (3554 vs 3446, inside the noise).
   - Only hpwl moves, about 3% down.
   - The one full route per arm puts b between the two a routes.
   - The detector does not suggest the parts that matter here, the RN banks
     and the SN74LVC1T45 banks. It declines the buffer banks as "bridges".
2. **(c), placing the key parts at the human pose, routes clearly better.**
   - Failed nets fall 39->15, 36->14 and 29->21 on seeds 0-2 (104 -> 50).
   - Crossings fall 33%, and the spread is lower.
   - The full route has the fewest broken nets (11 vs 20 for the best a).
   - The structure that helps is the one the human drew, not the one the
     detector suggests.
3. **`fixed_poses[]` cannot express (c) on this board.**
   - Stage 0 refused 15 of the 30 human poses: "courtyard within 0.02mm (the
     ladder's floor)". The human abuts courtyards at 2.8 mm buffer pitch, and
     puts U30 against FID8.
   - A refused entry is never seated (by contract), so those 15 parts, U30
     among them, end up unseated. That is the arm cf row: 15 unseated, 4.43x
     the human's crossings.
   - Arm c used a file lock instead, which is the route that works today.

