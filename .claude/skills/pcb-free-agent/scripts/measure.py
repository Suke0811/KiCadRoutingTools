#!/usr/bin/env python3
"""Where a pcb-free-agent session's wall clock went, from its transcript.

    python3 -X utf8 .claude/skills/pcb-free-agent/scripts/measure.py [SESSION.jsonl]
        [--root REPO] [--json OUT]

With no SESSION, reads the newest top-level transcript under
~/.claude/projects/<slug of --root>/ (default --root: this checkout).
Subagent transcripts in <session>/subagents/ are reported separately.

Reports:
- wall clock;
- tool calls by tool;
- repo scripts run;
- how long the agent spent WAITING on its own jobs (`until`/`sleep` polls and
  Monitor calls) versus other tool time versus model time;
- tokens, de-duplicated by message id (a streamed message repeats its usage
  per content block);
- any use of a forbidden entry point: the retired staged drivers. Every
  `converge.py` verb is allowed (the skill hands the agent all of py_placer/);
  they are COUNTED per verb, so a report can say how the ledger was used.

A line that does not parse is counted in `unparsed_lines`, never dropped.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys

KRT_TOOL = {'scope': ['combined'], 'kind': 'utility'}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
SHELLS = ('Bash', 'PowerShell')
SCRIPT_RE = re.compile(r'([\w./\\-]*\w\.py)\b')
FORBIDDEN_SCRIPTS = ('loop_driver.py', 'placement_driver.py')
#: converge's own subcommands. Matching a closed set means an argument that
#: merely follows the script name (`grep x converge.py py_tools/y.py`) is not
#: read as a verb.
CONVERGE_VERBS = ('poses', 'where', 'record', 'step-back', 'replay', 'status',
                  'verdict')
CONVERGE_VERB_RE = re.compile(r'converge\.py["\']?\s+(%s)(?![\w./\\-])'
                              % '|'.join(re.escape(v) for v in CONVERGE_VERBS))
WAIT_RE = re.compile(r'(^|[;&|]\s*|\bdo\s+)(until|sleep)\b')


def project_dir(root):
    slug = re.sub(r'[^A-Za-z0-9]', '-', os.path.abspath(root))
    return os.path.join(os.path.expanduser('~'), '.claude', 'projects', slug)


def _ts(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def read(path):
    rows, bad = [], 0
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad += 1
    return rows, bad


def tally(rows):
    tools, scripts, tokens = (collections.Counter() for _ in range(3))
    forbidden, seen, uses, results = [], set(), {}, {}
    first = last = None
    turns = agents = 0
    verbs = collections.Counter()
    for r in rows:
        if r.get('timestamp'):
            t = _ts(r['timestamp'])
            first, last = min(first or t, t), max(last or t, t)
        m = r.get('message') or {}
        content = m.get('content')
        if r.get('type') == 'assistant':
            if m.get('id') and m['id'] not in seen:
                seen.add(m['id'])
                turns += 1
                for k, v in (m.get('usage') or {}).items():
                    if isinstance(v, int):
                        tokens[k] += v
        if not isinstance(content, list):
            continue
        for b in content:
            if b.get('type') == 'tool_result':
                results[b.get('tool_use_id')] = r.get('timestamp')
            if b.get('type') != 'tool_use':
                continue
            name, inp = b.get('name'), b.get('input') or {}
            tools[name] += 1
            uses[b.get('id')] = (r.get('timestamp'), name, inp)
            if name == 'Agent':
                agents += 1
            if name in SHELLS:
                cmd = str(inp.get('command', ''))
                hits = {os.path.basename(s.replace('\\', '/'))
                        for s in SCRIPT_RE.findall(cmd)}
                scripts.update(hits)
                for f in sorted(hits & set(FORBIDDEN_SCRIPTS)):
                    forbidden.append({'hit': f, 'command': cmd[:300]})
                if 'converge.py' in hits:
                    verbs.update(CONVERGE_VERB_RE.findall(cmd))
    wait = work = 0.0
    for k, (t0, name, inp) in uses.items():
        if not (t0 and results.get(k)):
            continue
        d = (_ts(results[k]) - _ts(t0)).total_seconds()
        cmd = str(inp.get('command', ''))
        if name == 'Monitor' or (name in SHELLS and WAIT_RE.search(cmd)):
            wait += d
        else:
            work += d
    wall = (last - first).total_seconds() if first else 0.0
    return {'wall_clock': str(last - first) if first else None,
            'wall_seconds': wall,
            'waiting_on_jobs_seconds': round(wait, 1),
            'other_tool_seconds': round(work, 1),
            'model_and_idle_seconds': round(max(0.0, wall - wait - work), 1),
            'assistant_turns': turns, 'tool_calls': sum(tools.values()),
            'tools': dict(tools.most_common()),
            'repo_scripts': dict(scripts.most_common()),
            'agent_spawns': agents,
            'converge_record_calls': verbs.get('record', 0),
            'converge_verbs': dict(verbs),
            'tokens': dict(tokens), 'forbidden_uses': forbidden}


def measure(path):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise SystemExit(f'refuse: {path} is not a real non-empty file')
    rows, bad = read(path)
    out = {'session': path, 'main': dict(tally(rows), unparsed_lines=bad),
           'subagents': {}}
    for p in sorted(glob.glob(os.path.join(os.path.splitext(path)[0],
                                           'subagents', '*.jsonl'))):
        srows, sbad = read(p)
        out['subagents'][os.path.basename(p)] = dict(tally(srows),
                                                     unparsed_lines=sbad)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('session', nargs='?')
    ap.add_argument('--root', default=ROOT,
                    help='the checkout the session ran in (default: this one)')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv)
    path = a.session
    if not path:
        cands = sorted(glob.glob(os.path.join(project_dir(a.root), '*.jsonl')),
                       key=os.path.getmtime)
        if not cands:
            raise SystemExit(f'refuse: no transcript under {project_dir(a.root)}')
        path = cands[-1]
    out = measure(path)
    print(json.dumps(out, indent=2))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2)
    return 1 if out['main']['forbidden_uses'] else 0


if __name__ == '__main__':
    sys.exit(main())
