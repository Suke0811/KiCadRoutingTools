---
name: pcb-free-agent
description: Places and/or routes a KiCad board with the agent choosing its own steps. The repo's CLIs are the toolbox, and one independent verifier checks the result. Modes are full (place + route), place (placement only) and route (routing only). The skill sets the goal, the stop rules, the traps to avoid and the hand-back (board, film, report), not a procedure. Use it for a from-scratch or unplaced board, for re-placing, or for routing a placed board end to end.
---

# PCB free agent

You get a board, a goal and a toolbox, and you decide the steps. This skill
replaces the staged placement and combined drivers. It keeps the evidence,
because the verifier and the grader measure the board, but it does not
prescribe the process.

Invocation: `/pcb-free-agent <mode> <board.kicad_pcb> [intent.json]`, where
mode is `full`, `place` or `route`. With no mode, `full` for an unplaced board
and `route` for a placed one.

**Measured basis.** Two runs used this contract before it became a skill:
- **esp_prog, from a pile:** DONE in 12 min, 6 vias. The staged loop took 3h54m
  to 39 vias.
- **glasgow_revC, all 264 parts piled and unlocked:** blocking 15 in 7h56m. The
  staged loop took ~32 h to reach 35 on an easier input.

## 1. The goal, per mode

| mode | input | DONE means | better, once DONE |
|---|---|---|---|
| `full` | an unplaced or placed board | `board_score` blocking 0, zero unrouted, zero broken, `check_complete` DONE | fewer vias, then less copper_mm, then fewer segments |
| `place` | an unplaced or badly placed board | `check_assembly` buildable, `check_floorplan --intent` 0 errors, no pad or graphic copper off the outline, mechanical facts met | fewer floorplan warnings, then lower hpwl, then fewer airwire crossings (`render_placement --json-out`) |
| `route` | a placed board | the same as `full`, **with no part moved** | the same as `full` |

- **"Better" is lexicographic, never a weighted sum.** A lower via count never
  buys back an open net.
- **Matching the original layout does not count.** A human layout is a
  benchmark to approach, not a pose to match.

## 2. Before the first command

- **Declared facts win.** If the board has a sibling
  `<board>.design-brief.json` or `mechanical.json`, compile the intent from it:
  `python3 -X utf8 py_tools/check_floorplan.py <board> --emit-intent <intent.json>`.
  If the user states a mechanical fact (a connector's edge, a mounting-hole
  position), it is a requirement, and the verifier checks it.
- **Nothing is sacred except a KiCad lock.** The tools never move a locked part
  (`(locked yes)`), and there is no override. For a from-scratch experiment
  with everything off the board, build the input with
  `python3 -X utf8 .claude/skills/pcb-free-agent/scripts/make_unplaced.py <src> <dst>`.
  It piles every pad-bearing part off the outline and removes each moved
  part's lock.
- **Work in a run directory**, `wk/<run>/`. Copy every board with
  `python3 -X utf8 py_router/copy_board.py <src> <dst>`, never a bare `cp`,
  because the `.kicad_pro` beside a board carries its DRC floor.
- **Git Bash:** `export MSYS2_ARG_CONV_EXCL='*'` before any command that
  carries a net name. Quote `--nets '*'`.

## 3. The toolbox

Everything in `py_placer/`, `py_router/`, `py_tools/` and `docs/` is yours.
Read `--help` before assuming a flag does not exist. Two runs declared
"no lever left" while the lever sat unread in `--help`.

| job | tools |
|---|---|
| score (the authority on `blocking`) | `py_tools/board_score.py <board> --intent <i> --json <out>`; `check_complete.py <board> --intent <i>` (fails closed) |
| place | `py_placer/place_seed.py` (about 5–15 min on a 250-part board), `place_pose.py`, `place_portfolio.py` (on a *seeded* board, never on a pile), `place_fanout_clearance.py` |
| check a placement | `py_tools/check_assembly.py`, `py_tools/check_floorplan.py --intent`, `py_tools/render_placement.py --json-out` (then LOOK at the PNG) |
| route | `py_router/route_planes.py`, `py_router/bga_fanout.py`, `py_router/route.py`, `py_router/route_diff.py`, `py_router/repair_planes.py` |
| check a routed board | `py_router/check_connected.py`, `py_router/check_drc.py --baseline <input>`, `py_router/check_weird.py` |
| other skills | `plan-pcb-routing` (the routing recipe and its analysis helpers), `diagnose-routing-failures`, `review-routed-board` |

## 4. Traps measured in real runs (read these)

- **`place_pose` "legal" is not "buildable".** It does not see a same-net pad
  stacked on another part's pad (#1064). After every pose change, run
  `check_assembly`.
- **`render_placement`'s pad-clearance list uses bounding boxes.** It can flag
  an oval pad that `check_drc` passes (#1065). `check_drc` and `place_pose`
  are the truth.
- **A plain `route.py` output is not DONE.** `check_complete` refuses the
  in-pad wiggles the router keeps on purpose (#1063). Budget for a cleanup,
  and measure it with `check_weird`. One `check_weird` per candidate is too
  slow above a few thousand segments, so batch the candidates.
- **`route.py`'s own failure tally undercounts** after reconciliation laps
  (#1069). Count open nets with `check_connected` or `board_score`.
- **The decap tools have holes:**
  - `place_seed --repair` reports decap violators as "repaired" with 0 moved
    (#1066);
  - `place_fanout_clearance` can move a cap past `decap_pin_distance`
    silently (#1067);
  - `place_seed --reseat`'s intent basis ignores decap errors (#1068).

  Re-run `check_floorplan --intent` after each of these tools.
- **The routing skill's tuned env knobs** (`KICAD_GLOBAL_PLAN_RIVER` and the
  others) produced via hole-to-hole DRC on glasgow (#1070). Check DRC after
  any env change.
- **Around a 0.8 mm BGA, the router can run out of lanes.** Two changes that
  measured wins on glasgow:
  - finer tracks and vias (`--track-width 0.0762 --clearance 0.0889 --via-size 0.25 --via-drill 0.15`);
  - a cheaper ground-plane layer cost (`--layer-costs`).

  Both go below the board's authored floors, so disclose that
  (`check_complete --authored-from` reports it).

## 5. Rules

1. **You choose the steps.** Do not re-create a staged driver. The stop rules
   and the verifier are the only process.
2. **Stop rules:**
   - **First reach DONE**; nothing else before it.
   - **Watch long jobs.** Never leave a background job unwatched for more than
     20 minutes, and kill a search whose best has not improved in the last
     third of its run.
   - **After DONE, optimise in bounded rounds.** Stop when two consecutive
     rounds each cut vias by less than 5 % (in `place` mode: hpwl by less
     than 2 %).
   - **If DONE will not come:** after three consecutive DIFFERENT approaches
     that each fail to lower `blocking` (measured, not argued), stop and ship
     the best board, with every remaining blocker itemised with its
     measurement.
   - **Hard cap:** 10 hours of wall clock, unless the user sets another.
3. **An "impossible" claim needs its measurement.** "I tried A–F" is not a
   measurement. Read the whole log block, not only the first refusal line.
4. **One verifier, at most 3 calls.** When you believe you have your best
   board, spawn ONE fresh subagent (not a fork) with
   `references/verifier.md`, filled in for your mode, board, sha256, baseline
   and intent. On FAIL, fix what it names and continue. Spawn no other
   subagents unless the user asks.
5. **Record milestones for the film:** the first legal placement, each kept
   placement, the first routed board, the first DONE, each improvement, the
   final board, and tried-and-worse boards with `--rejected`.
   ```bash
   python3 -X utf8 py_tools/board_score.py <board> --intent <i> --json <board>.score.json --quiet
   python3 -X utf8 py_placer/converge.py record --ledger wk/<run>/ledger.jsonl \
       --board <board> --kind placement --parent <the board it was made from> \
       --lever "<what you did, one line>" --score-file <board>.score.json
   ```
   Use `--kind completion` for a routed board. The film's placement panels are
   drawn from the `placement` rows.

## 6. Hand-back

1. **The board**, with its `.kicad_pro`, and its sha256.
2. **The film**:
   ```bash
   python3 -X utf8 py_tools/make_film.py --from-ledger wk/<run>/ledger.jsonl \
       --theme light --aspect 4:3 --layout sidebar --panels xray+iso \
       --floorplan-intent <intent.json> -o wk/<run>/<run>_film.mp4
   ```
   Look at a few frames before you call it done.
3. **`wk/<run>/REPORT.md`**, containing:
   - **the result first:** a table of the mode's DONE conditions with measured
     values, plus vias / copper_mm / segments for routed modes;
   - **a timeline** from your first command: first legal placement, first
     fully routed board, first DONE, final board, verifier call(s);
   - **where the time went:** working vs waiting on long jobs;
   - **what worked and what didn't**, each with its measurement;
   - **tool gaps**, including any tool that said "fine" about something that
     was not; check the open issues first (`gh issue list --search`);
   - **each verifier verdict.**
4. **Independent grade and timing**, for the report's own table, never
   replacing the verifier:
   ```bash
   python3 -X utf8 .claude/skills/pcb-free-agent/scripts/grade.py <board> --baseline <input> --intent <i> --mode <mode>
   python3 -X utf8 .claude/skills/pcb-free-agent/scripts/measure.py --root .
   ```
