# #1051 evidence: glasgow from scratch, four arms, against the human layout

Produced by `tests/fixtures/1051/glasgow_three_arm.py`. Only the per-arm/seed
JSON results are committed. The boards are regenerable and are not
(`place_seed` is deterministic per seed).

## What was run

- **Input:** run 32's `wk/run32/glasgow_unplaced.kicad_pcb`, staged with
  `copy_board.py`. Its SHA-256 is in `setup.json` and every record
  (`unplaced_sha256`).
- **Intent:** run 32's intent, `tests/fixtures/1051/glasgow_run32.intent.json`.
  It declares `decaps.max_distance_mm` 2.5 and does NOT declare
  `decaps.seat_owners_first`, so since e1f325789 stage 2.4 seats no owner ICs
  in any arm. Declared rows (arm b) still seat their host first.
- **Seeding:** `place_seed --clearance 0.2 --force`, polish ON, seeds 0-4.
  `--force` is needed because the run-32 pile reads as placed: its connectors
  and holes are file-locked at their real poses.
- **Grading:** every arm is graded under the base intent as the common ruler.

| arm | what differs |
|---|---|
| a | nothing: the current seeder |
| b | every `check_floorplan --suggest-arrays` row declared as `arrays[]` (20 rows, accepted wholesale), then seed + quench |
| c | "the AI places the key parts": U30, RN1-RN12 and the 17 SN74LVC1T45 buffers written at their **human** pose (`kicad_files/glasgow_revC.kicad_pcb`) and stamped `(locked yes)` in the input board, then the rest seeded |
| cd | the same 29 RN/buffer poses **declared** as intent `fixed_poses[]` (stage 0 seats them); U30 file-locked at its human pose exactly as in c |

**Why U30 is file-locked in cd.** U30's human pose overlaps FID8 by
1.15 x 1.15 mm. FID8 is itself file-locked at its human pose in the input, so
stage 0 refuses a U30 declaration by design, and declaring FID8 as well would
change nothing. Leaving U30 to the seeder would make cd differ from c in two
ways at once. With U30 locked, c and cd differ ONLY in how the 29 small parts
are held: a file lock versus a declaration.

**What the detector suggests here** (the 20 rows in `setup.json`):
- Four 2-member RN rows: RN1/RN2 and RN7/RN8 serving U30, RN3/RN4 serving J3,
  RN9/RN10 serving J2.
- It DECLINES RN5/RN6, RN11/RN12 and both SN74LVC1T45 banks as "bridges"
  between the host and a second part.
- So 8 of the 12 RN parts get a row in arm b (four 2-member rows), and none
  of the 17 buffers do.

**The probe is nearly a whole-board route.** It routes 202 nets: every net of
fanout <= 20 on a key part or a detector-row member, fixed off the unplaced
board. That is 80% of glasgow's 251 nets. `test_placement_probe`'s own
`MAX_SCOPE_FRACTION` (0.5) would refuse it, but that cap only runs on the
`--intent` path, which is not used here. It is the same scope for every
comparison, with arm a as OFF and the same seed, so the comparisons are fair.
It is just not a scoped probe.

**Which crossings figure.** Crossings and hpwl are `render_placement`'s
figures. `place_seed`'s own `JSON_SUMMARY` crossings are recorded beside them
(`seed_run.seed_crossings`). They can differ: at 5712eea2e, by up to 40 on
a/b seed 3.

## Commands

```bash
SRC=C:/Users/rob/Documents/prive/git/KiCadRoutingTools/wk/run32/glasgow_unplaced.kicad_pcb
D=tests/fixtures/1051/glasgow_three_arm.py
# seeds: one process per arm
for arm in a b c cd; do
  python -X utf8 $D --src $SRC --workdir W_$arm --arms $arm --probe-seeds &
done; wait
# errors-by-rule re-grade; refuses if any headline number moves
python -X utf8 $D --regrade --arms a b c cd --reuse W_a W_b W_c W_cd
# probes, one process per (seed, arm)
for s in 0 1 2; do for arm in b c cd; do
  python -X utf8 $D --src $SRC --workdir P_${arm}_$s --arms a $arm --seeds $s \
      --probe-seeds $s --probe-arms $arm --reuse W_a W_$arm &
done; done; wait
python -X utf8 $D --table
```

The full-board routes use `$D --route ARM:SEED --reuse W_x --workdir R`, then
`$D --regrade-route ARM:SEED --reuse R`.

## Results (at b8575189e)

### The routed outcome

**Probe.** Seeds 0-2, arm a as OFF, same seed, same 202-net scope. The ladder
is failed nets / open nets / unconnected pad pairs / vias, OFF -> ON.

| seed | a -> b | a -> c |
|---|---|---|
| 0 | 38 -> 26 / 1 -> 1 / 28 -> 28 / 503 -> 468, better | 38 -> **22** / 1 -> 1 / 28 -> 16 / 503 -> 388, better |
| 1 | 39 -> 40 / 0 -> 2 / 32 -> 29 / 461 -> 495, **worse** | 39 -> **13** / 0 -> 0 / 32 -> 10 / 461 -> 419, better |
| 2 | 32 -> 44 / 1 -> 0 / 26 -> 33 / 437 -> 491, **worse** | 32 -> **15** / 1 -> 0 / 26 -> 11 / 437 -> 394, better |
| failed nets, total | 109 -> 110 | 109 -> 50 |

**Arm cd.** Every cd board is pose- and lock-identical to the c board of the
same seed: 272 footprints, x/y/rotation/side/locked all equal, seeds 0-4. This
is recorded per seed in `armcd_s*.json` as `pose_identical_to`, checked by
`--pose-identity c cd`.

What that comparison covers: every footprint's x, y, rotation, side and lock
state. It does NOT compare the two board files whole; they carry per-run
UUIDs. The router's input is the parts' poses on an otherwise identical
unplaced board, and the probe is deterministic, so a->cd is expected to equal
a->c.

The seed-0 a->cd probe was run anyway, as a check: 38 -> 22 / 1 -> 1 /
28 -> 16 / 503 -> 388, the same as a->c on every rung. cd seeds 1-2 were not
probed, on that basis.

**Full-board route.** Not re-run at this commit. Under this machine's load a
route takes 1.5-2.5 h per board. The four routes of the previous round are
kept in `recorded_5712eea2e/`:
- They ran the same chain on the boards committed in 5712eea2e, not on
  these. Those boards were SEEDED at 0a2a3358e (arm c at 43eae2deb). The
  routes themselves ran at 43eae2deb, the commit their records carry.
- The engine is identical between those two commits.
- At that engine, stage 2.4 was armed by the decap limit, so the a and b
  boards differ from today's. Arm c used the same method as today.

| board | nets with issues | unrouted | broken |
|---|---|---|---|
| a seed 4 (best a) | 20 | 0 | 20 |
| a seed 0 | 40 | 3 | 37 |
| b seed 0 | 26 | 1 | 25 |
| c seed 1 | 11 | 0 | 11 |

Treat these as history, not as a measurement of these boards.

### Placement proxies

Measured by `render_placement` at clearance 0.2 with no ignored nets. The
human board measures 1352 crossings and 3641 mm hpwl. At this commit,
`place_seed`'s own crossings figure equals render's on all 20 seeds.

| arm | crossings (mean +- sd, n=5) | x human | hpwl | x human |
|---|---|---|---|---|
| a | 3748 +- 309 | 2.77 | 5346 +- 92 | 1.47 |
| b | 3785 +- 300 | 2.80 | 5226 +- 239 | 1.44 |
| c | 2371 +- 78 | 1.75 | 4410 +- 94 | 1.21 |
| cd | 2371 +- 78 (identical boards) | 1.75 | 4410 +- 94 | 1.21 |

### Legality

- Every seed of every arm exits `place_seed` 4, with a non-empty grade under
  its own intent.
- No seed leaves a part unseated.
- Under the base intent, the ERRORS on every seed are exactly `legality` 1
  plus `decap_distance` plus `decap_pin_distance`
  (`grade.floorplan_base_errors_by_rule`). `pins_to_edge` and the other decap
  rules are warnings.
- `seed_run.grade_errors` is `place_seed`'s own count. It is smaller than
  `floorplan_own_errors` on some seeds, for example c seed 1: 13 vs 17.
  - It is graded under the same intent, but `_split_pinned` leaves out every
    error whose part is `(locked yes)` in the written board or matches
    `must_lock`.
  - Measured: c seed 1 excludes 4, on C1, U22 and U30 (twice), which gives
    17 - 4 = 13. b seed 0 excludes 1, on C1: 38 - 1 = 37.

| arm | errors per seed | `decap_pin_distance` | `decap_distance` |
|---|---|---|---|
| a | 31-37 | 23-29 | 6-10 |
| b | 26-36 | 20-28 | 5-7 |
| c / cd | 17-19 | 10-13 | 3-8 |

In the previous round, b seed 2 also carried one `zone_containment` error.
This round has none.

**Why a's errors rose from 8-16 to 31-37 since 5712eea2e.** Stage 2.4 is
opt-in now (`decaps.seat_owners_first`), and this intent does not opt in. So
fewer ICs are placed when the decap pin stage runs: it claims 29 caps in arm a
(81-82 before), 50-51 in b and 60 in c. The locked FPGA and buffers give c's pin
stage its owners.

## Findings, plainly

1. **(b), the detector's rows declared, does NOT route better than (a).**
   - Probe failed nets total 109 -> 110: better on seed 0, worse on seeds 1
     and 2.
   - Crossings are no better (3785 vs 3748). hpwl is about 2% lower.
   - The detector gives rows to 8 of the 12 RN parts (RN1/2, RN3/4, RN7/8,
     RN9/10, each a 2-member row) and to none of the 17 buffers. It declines
     RN5/6, RN11/12 and both buffer banks as bridges.
   - Most of the structure the human used is outside what it suggests.
2. **(c), the key parts at the human pose, routes clearly better.**
   - Probe failed nets 109 -> 50, better on all three seeds.
   - Crossings are 37% lower, with a quarter of a's spread.
3. **(cd): yes, the winning structure can now be expressed by declaration.**
   - Declaring the 29 RN/buffer poses as `fixed_poses[]` seats all 29 at
     b8575189e.
   - The result is the SAME board as the file-locked arm, seed for seed.
   - One exception: U30. Its human pose overlaps FID8 by 1.15 x 1.15 mm, so
     stage 0 refuses it as a declaration. It stays file-locked here, and a
     brief or intent cannot place it where the human did.

