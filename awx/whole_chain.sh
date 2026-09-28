#!/bin/zsh
# whole_chain.sh K OUTDIR [ROUNDS] -- the whole route on rung K, end to end: the fanout choosing every net's tooth and
# berth with the whole route's ends model (fanout_from_plan, PLAN_JUDGE=ends), the solve (whole_solve), the loop
# (whole_loop.sh: geometry, polish, audits, snaps) and the route all at once (route_lanes), graded (check_connected,
# check_drc). When the loop does not pass, the ends its audits found crowded (whole_gate --hot -> whole_feedback) go
# back to the fanout (FEEDBACK=), which chooses again INCREMENTALLY from the previous round's board; up to ROUNDS
# fanouts (default 3). BASE (default fb_t2q_pairs.kicad_pcb) is the bench, DEST (default DU1) its destination part.
# Exits 0 with OUTDIR/rN/seq.kicad_pcb routed, connected and DRC-clean; the last line is the grade:
#   WHOLE K=.. round=.. lanes=../.. vias=.. copper=..mm connected=0|1 drc=0|1 secs=..
HERE=${0:A:h}
K=$1; o=${2:A}; R=${3:-3}; mkdir -p $o; cd $HERE; t0=$(date +%s)
BASE=${BASE:-fb_t2q_pairs.kicad_pcb}; DEST=${DEST:-DU1}
export OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TAUT_MEMO=${TAUT_MEMO:-1} PROBE_MEMO=${PROBE_MEMO:-1}
export PYTHONHASHSEED=7 PLAN_PAGES=1 PLAN_JUDGE=ends BRAID_PAIRS=1 PLAN_PAIRS=1 BRAID_EXACT_PAGES=0 PLAN_PAGES_SIDERS=2
NETS=$(python3 coherent_nets.py $K --board=$BASE 2>/dev/null | tail -1)
FB=$o/feedback.json; rm -f $FB; prev=
for r in $(seq 1 $R); do
  d=$o/r$r; mkdir -p $d; echo $NETS | tr ',' '\n' > $d/nets.lines
  echo "=== fanout round $r"
  ( [ -f $FB ] && export FEEDBACK=$FB; [ -n "$prev" ] && export INCREMENTAL=$prev/fo.plan.json
    python3 fanout_from_plan.py $d/fo.kicad_pcb $K --board=$BASE > $d/fo.log 2>&1 )
  echo "  fanout exit $? at $(( $(date +%s) - t0 )) s"
  grep -E "plan model" $d/fo.log | cut -c1-220
  [ -f $d/fo.kicad_pcb ] || exit 1
  # the same ends as the round before (feedback it priced but did not follow): the rest of the round would be the same
  if [ -n "$prev" ] && python3 -c "import json, sys; sys.exit(0 if json.load(open(sys.argv[1])) == json.load(open(sys.argv[2])) else 1)" $d/fo.plan.json $prev/fo.plan.json; then
    echo "=== fanout round $r laid round $((r - 1))'s ends again"; r=$((r - 1)); break
  fi
  export BENCH=$d/fo.kicad_pcb NETS DEST
  python3 whole_solve.py $d/solve.json > $d/solve.log 2>&1
  grep -E "whole_solve:|workers:" $d/solve.log | cut -c1-200
  [ -f $d/solve.json ] || { echo "  no proved plan -- stopping"; echo "WHOLE K=$K round=$r lanes=0/0 vias=0 copper=0mm connected=0 drc=0 secs=$(( $(date +%s) - t0 ))"; exit 2; }
  ./whole_loop.sh $d/solve.json $d/loop 6 > $d/loop.log 2>&1; rc=$?
  grep -E "^=== round|smooth:|NOT CONVERGING|passes" $d/loop.log | cut -c1-170
  echo "  loop exit $rc at $(( $(date +%s) - t0 )) s"
  if [ $rc -eq 0 ]; then
    RR=(--plan $d/loop/plan.json --board $BENCH --nets $NETS --dest $DEST)
    unset BENCH
    BRAID_PAIR_SLACKS=0 python3 route_lanes.py all $RR --mode seq --write $d/seq.kicad_pcb > $d/route_seq.log 2>&1
    sm=$(grep -E "^SUMMARY" $d/route_seq.log); echo "  all at once: $sm"
    pats=(); for n in $(cat $d/nets.lines); do pats+=("*$n"); done
    python3 ../py_router/check_connected.py $d/seq.kicad_pcb --nets $pats > $d/conn.log 2>&1; cc=$?
    python3 ../py_router/check_drc.py $d/seq.kicad_pcb --nets $pats --clearance-margin 0.1 > $d/drc.log 2>&1; dc=$?
    lanes=$(echo "$sm" | grep -oE "[0-9]+/[0-9]+ in band" | cut -d' ' -f1)
    vl=$(python3 -c "
import sys, math
sys.path.insert(0, '../py_router')
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    from kicad_parser import parse_kicad_pcb
    p = parse_kicad_pcb('$d/seq.kicad_pcb')
nets = set(open('$d/nets.lines').read().split())
nm = {i: n.name.split('/')[-1] for i, n in p.nets.items()}
print(sum(1 for v in p.vias if nm.get(v.net_id) in nets),
      round(sum(math.hypot(s.end_x - s.start_x, s.end_y - s.start_y) for s in p.segments if nm.get(s.net_id) in nets)))")
    echo "WHOLE K=$K round=$r lanes=$lanes vias=${vl% *} copper=${vl#* }mm connected=$(( cc == 0 )) drc=$(( dc == 0 )) secs=$(( $(date +%s) - t0 ))"
    exit $(( cc != 0 || dc != 0 ))
  fi
  unset BENCH
  hots=()
  for a in $d/loop/p*.audit(N) $d/loop/q*.audit(N); do j=${a%.audit}.json; h=${a%.audit}.fbhot.json
    python3 whole_gate.py $j $a --hot $h > /dev/null 2>&1; hots+=($h); done
  hots+=($d/loop/hs*.json(N))                # the snapped plans' places (whole_loop: the audit's and the lint's)
  fbl=$(python3 whole_feedback.py $d/fo.plan.json $FB $hots); echo "$fbl"
  # nothing new for the fanout: the next round would lay the same ends from the same feedback (zynq K42's three
  # rounds, and K38's second and third, were the same run again)
  [[ $fbl == *"whole_feedback: 0 new"* ]] && { echo "=== the feedback adds nothing new: another fanout lays the same ends"; break; }
  sb=$(grep -oE 'source board: [^,]+' $d/fo.log | tail -1 | sed 's/source board: //')
  prev=$d; [ -f $d/$sb ] && BASE=$d/$sb
done
echo "WHOLE K=$K round=$r lanes=0/0 vias=0 copper=0mm connected=0 drc=0 secs=$(( $(date +%s) - t0 ))"
exit 3
