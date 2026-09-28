#!/bin/zsh
# whole_loop.sh SOLVE.json OUTDIR [ROUNDS] -- the whole-route plan, every step fed by a MEASUREMENT of the one before:
#   geometry (whole_geo: the joint LP, with every side flip measured so far)
#   -> polish (whole_polish: the audit's own measures met in board xy)
#   -> audit (whole_audit through whole_gate: what the router will be handed)
#   -> side flips the polish could not avoid (an island it found no room beside, or one holding a lane's approach off
#      its stub): the geometry again on the SAME solve, before anything is snapped -- or, when the round has cuts or
#      findings as well, the solve again with them and the geometry with the flips, in one round
#   -> a smooth plan that passes: its PAIRS laid first as the pair router moves (whole_snap --pairs), the singles
#      fitted round them (whole_polish, the pairs held; where a single is short of room, the pairs laid again keeping
#      it -- whole_snap SNAP_KEEP) and SNAPPED onto the router's grid (whole_snap); audited, gated
#      and linted (the pair router's turning radius and straight dives) -- done
#   -> else the solve again (warm), with every cut so far -- the island / via cuts the geometry could not meet and the
#      via cuts of the pair dives the polish could not lay straight -- and every audit's findings so far as HISTORY
#      (whole_gate --hot: where the plan was short; the solve prices crossings and changes there by how many audits
#      found it so, whole_solve HIST). A finding with no cut to send -- a pitch, a shape, a dive with the pairs held or
#      snapped -- is still sent: its place, priced.
# The bench from BENCH / NETS / DEST (whole_ctx), under the chain's plan environment (set below).
# SEED_FLIPS / SEED_CUTS / SEED_HIST: comma lists of earlier polish / geometry / hot JSONs to start from. A HARNESS
# that runs the same bench again and again: it turns on the caches the router leaves off (STAGE_CACHE=1: a stage
# already run on the same inputs with the same code restored from awx/tmp/stage_cache, stage_cache.py; TAUT_MEMO=1:
# the braid's taut strings kept under awx/tmp/taut_memo) -- STAGE_CACHE=0 / TAUT_MEMO=0 run it without them.
# A loop that is NOT CONVERGING stops: each round is scored by how far its plan got (smooth, the pairs held, snapped)
# and its audit findings there (dive, static, shape, swim, pitch in the plan, any length outside its band), and two
# rounds in a row that fail to beat the best so far end it -- flips, cuts and prices that only move the findings about
# are not getting there, and every such round pays a solve.
# A finding at the ENDS -- within whole_feedback's reach of the teeth or the berths -- stops it too, at once when it is
# one no solve moves (a pitch or a static clearance there), else when it stands in two rounds running: only the
# fanout can move it (whole_feedback.py, FEEDBACK=) -- once the round has no new side flip left to try.
# Exit 0 with OUTDIR/plan.json the snapped plan that passed; 1 when no round got there; 3 when it stopped not
# converging; 4 when it stopped at crowded ends.
HERE=${0:A:h}
solve=${1:A}; out=${2:A}; rounds=${3:-6}
cd $HERE
# the braid's plan environment the planning reads (a pages-first sidecar's paging, its pairs)
export BRAID_PAIRS=1 BRAID_EXACT_PAGES=0 PLAN_PAGES_SIDERS=2
# every expensive stage through stage_cache.py: a stage whose script, arguments, environment and every file it read
# are unchanged is restored, not run -- on here, a harness's cache (STAGE_CACHE=0 runs them all)
export STAGE_CACHE=${STAGE_CACHE:-1} TAUT_MEMO=${TAUT_MEMO:-1}
ST=(python3 stage_cache.py)
mkdir -p $out
flips="${SEED_FLIPS:-}"; cuts="${SEED_CUTS:-}"; hist="${SEED_HIST:-}"
# the side flips in a comma list of polish outputs, every file's (a SEED_FLIPS list names several)
nflips() { python3 -c "import json,sys; print(len({tuple(x) for f in sys.argv[1].split(',') if f for x in json.load(open(f)).get('flips', [])}))" "$1"; }
# the findings in a gate line (whole_gate's summary): dive, static, shape, swim, pitch in the plan, band outside (0/1);
# a gate line without its counts (an audit that did not run to its end) counts as many
findings() { python3 -c "
import re, sys
s = sys.argv[1]
try:
    n = sum(int(re.search(k + r' (\d+)', s).group(1)) for k in ('dive', 'static', 'shape', 'swim'))
    n += int(re.search(r'pitch (\d+) in the plan', s).group(1))
    n += int(re.search(r'band broken (\d+)', s).group(1)) if 'band broken' in s else 0
    n += int(re.search(r'(\d+) lane\(s\) missing', s).group(1)) if 'missing' in s else 0     # a lane a snap could not lay
    print(n + (1 if float(re.search(r'band ([\d.]+) mm', s).group(1)) > 0 else 0))
except AttributeError:
    print(999)" "$1"; }
# an audit's findings as history: its hot places (whole_gate --hot), added when it names any
addhot() {
  python3 whole_gate.py $1 $2 --hot $3 > /dev/null
  [ "$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['hot']))" $3)" = "0" ] && return 1
  hist="${hist:+$hist,}$3"
}
# the solve again, warm, with every cut and every audit's history so far -- less an island cut a side flip has
# answered since (the flip puts that lane on the island's other side; the cut would keep holding it off the island)
resolve() {
  local s2=$out/s$((i + 1)).json
  python3 - "$cuts" "$flips" "$out/cuts$((i + 1)).json" "$out" "${SEED_FLIPS:-}" <<'PY'
import json, os, re, sys
fl = lambda fs: {tuple(x[:2]) for f in fs if f and os.path.isfile(f) for x in json.load(open(f)).get('flips', [])}
flipped = fl(sys.argv[2].split(','))
cuts, vcuts = [], []
for f in [f for f in sys.argv[1].split(',') if f]:
    c = json.load(open(f))
    # a cut from the geometry of round k whose flip that geometry had ALREADY been given (a polish of an earlier round
    # found it, or the seed): both sides of the island failed -- the solve hears of it. Only a cut the flip answers,
    # one from before it, is dropped (zynq K42: DQ10's cut at C98, made again after its flip, never reached the solve)
    m = re.search(r'/c(\d+)\.json$', f)
    k = int(m.group(1)) if m else 0
    given = fl(sys.argv[5].split(',') + [os.path.join(sys.argv[4], f'{nm}{j}.json') for j in range(1, k)
                                          for nm in ('p', 'q', 'qk')])
    cuts += [x for x in c.get('cuts', []) if (x['lane'], x['island']) not in flipped or (x['lane'], x['island']) in given]
    vcuts += c.get('vcuts', [])
json.dump({'cuts': cuts, 'vcuts': vcuts}, open(sys.argv[3], 'w'))
PY
  HINT=$solve CUTS=$out/cuts$((i + 1)).json HIST=$hist $ST --out $s2 -- whole_solve.py $s2 > ${s2%.json}.log 2>&1 || { tail -3 ${s2%.json}.log; exit 1; }
  grep -E "whole_solve|vias|check|history" ${s2%.json}.log | sed 's/^/  /'
  solve=$s2
}
# the round's score -- how far its plan got (a stage not reached a thousand) and its findings there -- against the best
PATIENCE=2                                 # rounds in a row without a new best
best=-1; best_i=0; stall=0
progress() {
  # (fresh: the round found side flips it has not tried -- not a stall, whatever its score)
  if [ $best -lt 0 ] || [ $1 -lt $best ]; then best=$1; best_i=$i; stall=0; elif [ "$2" != fresh ]; then stall=$((stall + 1)); fi
  if [ $stall -ge $PATIENCE ]; then
    echo "=== round $i: NOT CONVERGING -- score $1, the best $best at round $best_i, $PATIENCE rounds without a better one"
    exit 3
  fi
}
for i in $(seq 1 $rounds); do
  rm -f $out/hp$i.json                     # (a round that passes writes none: an earlier run's must not stand in for it)
  echo "=== round $i: geometry of $(basename $solve)${flips:+ (flips from $(basename ${flips##*,}))}"
  GEO_FLIPS_FROM=$flips $ST --out $out/g$i.json -- whole_geo.py $solve $out/g$i.json > $out/g$i.log 2>&1 || { tail -3 $out/g$i.log; exit 1; }
  $ST --out $out/p$i.json -- whole_polish.py $out/g$i.json $out/p$i.json > $out/p$i.log 2>&1 || { tail -3 $out/p$i.log; exit 1; }
  $ST -- whole_audit.py $out/p$i.json > $out/p$i.audit 2>&1 || { tail -3 $out/p$i.audit; exit 1; }
  gl=$(python3 whole_gate.py $out/p$i.json $out/p$i.audit)
  echo "$gl" | sed 's/^/  smooth: /'
  f=$(findings "$gl")
  before=$([ -n "$flips" ] && nflips "$flips" || echo 0)
  after=$(nflips $out/p$i.json)
  # the round's cuts -- the geometry's islands and via cuts, the polish's via cuts -- less an island cut that one of
  # the round's NEW flips answers (the flip puts that lane on the island's other side; the geometry has not tried it)
  n=$(python3 - "$out/g$i.json" "$out/p$i.json" "$flips" "$out/c$i.json" <<'PY'
import json, sys
g, p = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
old = {tuple(x) for f in sys.argv[3].split(',') if f for x in json.load(open(f)).get('flips', [])}
new = {tuple(x) for x in p.get('flips', [])} - old
cuts = [c for c in g.get('cuts', []) if (c['lane'], c['island']) not in new]
vcuts = g.get('vcuts', []) + p.get('vcuts', [])
json.dump({'cuts': cuts, 'vcuts': vcuts}, open(sys.argv[4], 'w'))
print(len(cuts) + len(vcuts))
PY
)
  passes=$(python3 whole_gate.py $out/p$i.json $out/p$i.audit > /dev/null && echo 1 || echo 0)
  [ $passes = 0 ] && addhot $out/p$i.json $out/p$i.audit $out/hp$i.json && n=$((n + 1))
  # a finding at the ENDS standing in two rounds running: the solve had its round and did not move it, the fanout must
  # (whole_feedback --repeat; the fanout's sidecar beside BENCH) -- stopped here rather than solving again and again.
  # Not while the round has new side flips: a flip is the geometry's own answer, still to be tried (K35 SA4 squeezed
  # between two resistors' pads by the berths, answered by going round them)
  sidecar=${BENCH%.kicad_pcb}.plan.json
  newflips=$([ "$after" -gt "$before" ] && echo 1 || echo 0)
  if [ $passes = 0 ] && [ $newflips = 0 ] && [ -f $out/hp$i.json ] && [ -f "$sidecar" ] \
      && python3 whole_feedback.py --now $sidecar $out/hp$i.json; then
    # ...and at once, when a finding there is one no solve moves (a pitch or a static clearance at the ends)
    echo "=== round $i: ENDS CROWDED -- findings at the ends no solve moves: the fanout's to change"
    exit 4
  fi
  if [ $passes = 0 ] && [ $newflips = 0 ] && [ $i -gt 1 ] && [ -f $out/hp$((i - 1)).json ] && [ -f $out/hp$i.json ] && [ -f "$sidecar" ] \
      && python3 whole_feedback.py --repeat $sidecar $out/hp$((i - 1)).json $out/hp$i.json; then
    echo "=== round $i: ENDS CROWDED -- the same findings at the ends two rounds running: the fanout's to change"
    exit 4
  fi
  if [ "$after" -gt "$before" ]; then
    progress $((2000 + f)) fresh
    flips=$out/p$i.json                    # the polish output carries every flip so far
    if [ "$n" = "0" ]; then
      echo "=== round $i: $((after - before)) new side flip(s) -> the geometry again on the same solve"
      continue
    fi
    # flips AND cuts or findings: both at once -- the solve with them, then the geometry with the flips (one round)
    cuts="${cuts:+$cuts,}$out/c$i.json"
    echo "=== round $i: $((after - before)) new side flip(s), and cuts or findings -> the solve again, then the geometry with the flips"
    resolve
    continue
  fi
  if [ $passes = 1 ]; then
    # the PAIRS first, laid as the pair router moves (its turning radius, its straight dives), then the singles
    # fitted round them (the polish, the pairs held) and snapped
    echo "=== round $i: the smooth plan passes -> the pairs laid first"
    if ! $ST --out $out/pairs$i.json -- whole_snap.py $out/p$i.json $out/pairs$i.json --pairs > $out/pairs$i.log 2>&1; then
      grep -q "^SNAP FAILED" $out/pairs$i.log || { tail -3 $out/pairs$i.log; exit 1; }
    fi
    grep -E "^snap:|FAILED" $out/pairs$i.log | sed 's/^/  /'
    if grep -q "^SNAP FAILED" $out/pairs$i.log; then
      # a pair the snap cannot lay: its dive nearest where it got stuck goes to the solve as a via cut (whole_snap's
      # dive_cuts), and the solve again; a pair with no dive to move there stops
      nd=$(python3 -c "import json, sys; d = json.load(open(sys.argv[1])).get('dive_cuts', []); json.dump({'vcuts': d}, open(sys.argv[2], 'w')); print(len(d))" $out/pairs$i.json $out/dc$i.json)
      [ "$nd" = "0" ] && { echo "=== round $i: a pair cannot be laid"; exit 1; }
      progress 1500
      cuts="${cuts:+$cuts,}$out/dc$i.json"
      echo "=== round $i: a pair cannot be laid at a dive -> the solve again, $nd dive(s) moved (via cuts)"
      resolve
      continue
    fi
    $ST --out $out/q$i.json -- whole_polish.py $out/pairs$i.json $out/q$i.json > $out/q$i.log 2>&1 || { tail -3 $out/q$i.log; exit 1; }
    $ST -- whole_audit.py $out/q$i.json > $out/q$i.audit 2>&1 || { tail -3 $out/q$i.audit; exit 1; }
    gq=$(python3 whole_gate.py $out/q$i.json $out/q$i.audit)
    echo "$gq" | sed 's/^/  pairs held: /'
    q=$out/q$i.json
    if ! python3 whole_gate.py $out/q$i.json $out/q$i.audit > /dev/null; then
      # the singles do not fit round the pairs: the pairs laid AGAIN keeping each single's room where it was short
      # (whole_snap SNAP_KEEP), then the singles fitted again round those
      python3 whole_gate.py $out/q$i.json $out/q$i.audit --hot $out/hk$i.json > /dev/null
      # (a pair that cannot be laid so is no plan: the pairs laid first stand, and their singles' places go to the
      # solve below; any other failure stops)
      if ! SNAP_KEEP=$out/hk$i.json $ST --out $out/pairs${i}k.json -- whole_snap.py $out/p$i.json $out/pairs${i}k.json --pairs > $out/pairs${i}k.log 2>&1; then
        grep -q "^SNAP FAILED" $out/pairs${i}k.log || { tail -3 $out/pairs${i}k.log; exit 1; }
        echo "  pairs laid again, the singles kept room: $(grep '^SNAP FAILED' $out/pairs${i}k.log)"
      fi
      if ! grep -q "^SNAP FAILED" $out/pairs${i}k.log; then
        $ST --out $out/qk$i.json -- whole_polish.py $out/pairs${i}k.json $out/qk$i.json > $out/qk$i.log 2>&1 || { tail -3 $out/qk$i.log; exit 1; }
        $ST -- whole_audit.py $out/qk$i.json > $out/qk$i.audit 2>&1 || { tail -3 $out/qk$i.audit; exit 1; }
        gk=$(python3 whole_gate.py $out/qk$i.json $out/qk$i.audit)
        echo "$gk" | sed 's/^/  pairs laid again, the singles kept room: /'
        python3 whole_gate.py $out/qk$i.json $out/qk$i.audit > /dev/null && q=$out/qk$i.json
      fi
    fi
    if [ $q = $out/q$i.json ] && ! python3 whole_gate.py $out/q$i.json $out/q$i.audit > /dev/null; then
      # the singles do not fit round the pairs: where they are short goes to the solve as history -- and the side
      # flips the polish found with the pairs held go to the next geometry, as a smooth polish's do (they were dropped)
      qf=$out/q$i.json; [ -f $out/qk$i.json ] && qf=$out/qk$i.json
      nq=$(python3 -c "import json, sys; o = {tuple(x) for f in sys.argv[1].split(',') if f for x in json.load(open(f)).get('flips', [])}; print(len({tuple(x) for x in json.load(open(sys.argv[2])).get('flips', [])} - o))" "$flips" $qf)
      if [ "$nq" != "0" ]; then flips="${flips:+$flips,}$qf"; echo "  pairs held: $nq new side flip(s) for the next geometry"; fi
      progress $((1000 + $(findings "$gq"))) $([ "$nq" != "0" ] && echo fresh)
      addhot $out/q$i.json $out/q$i.audit $out/hq$i.json || { echo "=== round $i: the singles do not fit round the pairs"; exit 1; }
      echo "=== round $i: the singles do not fit round the pairs -> the solve again, their places priced"
      resolve
      continue
    fi
    # (a single the snap cannot lay leaves the plan without it -- the gate fails it -- and where it got stuck goes to the
    # solve with the audit's findings below; any other failure stops)
    if ! $ST --out $out/plan.json -- whole_snap.py $q $out/plan.json > $out/snap.log 2>&1; then
      grep -q "^SNAP FAILED" $out/snap.log || { tail -3 $out/snap.log; exit 1; }
    fi
    grep -E "^snap:|FAILED" $out/snap.log | sed 's/^/  /'
    $ST -- whole_audit.py $out/plan.json > $out/plan.audit 2>&1 || { tail -3 $out/plan.audit; exit 1; }
    gs=$(python3 whole_gate.py $out/plan.json $out/plan.audit)
    echo "$gs" | sed 's/^/  snapped: /'
    python3 whole_lint.py $out/plan.json > $out/plan.lint 2>&1; lint=$(tail -1 $out/plan.lint)
    echo "  snapped: $lint"
    python3 whole_gate.py $out/plan.json $out/plan.audit > /dev/null && [ "$lint" = "LINT clean" ] && { echo "=== the plan passes: $out/plan.json"; exit 0; }
    # the snapped plan is short: where goes to the solve as history -- the audit's places and the lint's (a lane folded
    # at its end: the end it folds at), a finding with no place stops
    progress $(( $(findings "$gs") + $(grep -E '^LINT \S+ \S+ ' $out/plan.lint | grep -cvE '^LINT( [a-z-]+ [0-9]+,?)+$') ))
    cat $out/plan.audit $out/plan.lint > $out/plan.found
    addhot $out/plan.json $out/plan.found $out/hs$i.json || { echo "=== round $i: the snapped plan does not pass"; exit 1; }
    echo "=== round $i: the snapped plan does not pass -> the solve again, its places priced"
    resolve
    continue
  fi
  progress $((2000 + f))
  if [ "$n" = "0" ]; then echo "=== round $i: no flips, no cuts and no findings with a place left"; exit 1; fi
  cuts="${cuts:+$cuts,}$out/c$i.json"
  echo "=== round $i: cuts or findings -> the solve again"
  resolve
done
echo "=== no round passed"
exit 1
