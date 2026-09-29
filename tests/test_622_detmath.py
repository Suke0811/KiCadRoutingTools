#!/usr/bin/env python3
"""#622 `awx/detmath.py`: the whole route computes the same bits on every machine.

A Mac and a Linux box ran the K ladder to the same grades and via counts but
different copper (K41 1039 vs 995 mm): their C libraries round sin / cos /
atan2 / exp / log / pow and np.hypot differently in the last bit, and HiGHS
lands on another of an LP's equal optima. detmath computes the transcendental
functions from + - * / sqrt alone (fdlibm), every chain stage installs them
first, the chain writes `x * x` where it wrote the C library's `x ** 2`, and
the two LPs take a fixed tie-break and a rounded solution.

What this asserts:

1. THE BITS ARE RECORDED: detmath's answers on fixed inputs hash to one
   digest, the same on every machine -- the claim itself, checked wherever the
   suite runs (a Linux runner and a Mac both).
2. They are the functions they name: within a few ulp of the platform's.
3. install() swaps math's and numpy's, once, and the out-of-range fallback
   reaches the platform's own function (not a recursion into the swap).
4. Every awx script the chain's drivers run installs detmath BEFORE it imports
   the chain (whose modules compute constants as they load) -- or computes
   nothing, importing no math, numpy, scipy or chain module.
5. No module the chain loads raises a float to a power (`x ** 2` is the C
   library's pow: the same function the platforms round differently).
6. The LP helpers make an LP's answer a function of the model: a model with a
   face of optima solves to one point, by the interior point and the simplex
   alike.
"""
import ast
import hashlib
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWX = os.path.join(os.path.dirname(HERE), 'awx')
sys.path.insert(0, AWX)
import numpy as np  # noqa: E402
import detmath  # noqa: E402

FAIL = []


def check(ok, what):
    print(('  ok   ' if ok else '  FAIL ') + what)
    if not ok:
        FAIL.append(what)


def inputs():
    """fixed inputs from integer arithmetic alone (no generator whose floats could depend on the platform)"""
    xs, s = [], 12345
    for _ in range(4000):
        s = (s * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        xs.append((s >> 11) / float(1 << 53))                 # [0, 1), exact
    return xs


def ulp(a, b):
    ia = struct.unpack('<q', struct.pack('<d', a))[0]
    ib = struct.unpack('<q', struct.pack('<d', b))[0]
    return abs(ia - ib)


U = inputs()
CASES = {
    'sin': [(detmath.sin, math.sin, 1, (-60 + 120 * u,)) for u in U],
    'cos': [(detmath.cos, math.cos, 1, (-60 + 120 * u,)) for u in U],
    'tan': [(detmath.tan, math.tan, 3, (-1.5 + 3 * u,)) for u in U],
    'atan': [(detmath.atan, math.atan, 1, (-300 + 600 * u,)) for u in U],
    'atan2': [(detmath.atan2, math.atan2, 1, (-200 + 400 * u, -200 + 400 * v)) for u, v in zip(U, reversed(U))],
    'asin': [(detmath.asin, math.asin, 2, (-1 + 2 * u,)) for u in U],
    'acos': [(detmath.acos, math.acos, 2, (-1 + 2 * u,)) for u in U],
    'exp': [(detmath.exp, math.exp, 1, (-40 + 80 * u,)) for u in U],
    'log': [(detmath.log, math.log, 1, (1e-6 + 1e4 * u,)) for u in U],
    'pow2': [(detmath.pow, math.pow, 1, (-300 + 600 * u, 2.0)) for u in U],
    'pow1.5': [(detmath.pow, math.pow, 24, (1e-3 + 300 * u, 1.5)) for u in U],
}
# the digest of every answer above, recorded on one machine and asserted on all (item 1)
BITS = 'a63a408a40f49655'


def main():
    print('1-2. the bits, and the functions they name')
    h = hashlib.sha256()
    for name, rows in CASES.items():
        worst = 0
        for f, ref, tol, args in rows:
            v = f(*args)
            h.update(struct.pack('<d', v))
            worst = max(worst, ulp(v, ref(*args)))
        check(worst <= rows[0][2], f'{name}: within {rows[0][2]} ulp of the platform\'s (worst {worst})')
    for a, b, want in ((0.0, -1.0, math.pi), (-0.0, -1.0, -math.pi), (1.0, 0.0, math.pi / 2), (0.0, 0.0, 0.0),
                       (-1.0, -1.0, -3 * math.pi / 4)):
        check(detmath.atan2(a, b) == want, f'atan2({a}, {b}) == {want}')
    got = h.hexdigest()[:16]
    if BITS == 'RECORD':
        print(f'  record: BITS = {got!r}')
    check(BITS in ('RECORD', got), f'the answers hash to the recorded {BITS} (got {got}): the same bits as everywhere else')

    print('3. install')
    libm_sin = math.sin
    detmath.install(); detmath.install()
    check(math.sin is detmath.sin and math.atan2 is detmath.atan2 and math.pow is detmath.pow, 'math\'s functions are detmath\'s')
    check(np.hypot(3.0, 4.0) == 5.0 and float(np.hypot(np.array([1e-3]), np.array([2e-3]))[0]) == math.sqrt(1e-6 + 4e-6),
          'np.hypot is sqrt(a*a + b*b)')
    check(math.sin(1e6) == libm_sin(1e6), 'past the reduction\'s range: the platform\'s own sin, no recursion')
    check(float(np.interp(0.5, [0.0, 1.0, 2.0], [0.0, 10.0, 30.0])) == 5.0 and
          list(np.interp([-1.0, 2.0, 3.0], [0.0, 1.0, 2.0], [0.0, 10.0, 30.0])) == [0.0, 30.0, 30.0], 'np.interp keeps its contract')

    print('4. every chain stage installs first')
    # the driver names each stage it runs as a string ('whole_geo.py'); the checkers it names live in py_router
    driver = ast.parse(open(os.path.join(AWX, 'whole_route.py')).read())
    scripts = {n.value for n in ast.walk(driver) if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and re.fullmatch(r'[a-z_]+\.py', n.value) and os.path.isfile(os.path.join(AWX, n.value))}
    scripts.discard('stage_cache.py')                 # runs the stage in its own process, as __main__
    local = {f[:-3] for f in os.listdir(AWX) if f.endswith('.py')}
    check(len(scripts) >= 8, f'the drivers name {len(scripts)} stages: {sorted(scripts)}')
    for s in sorted(scripts):
        t = ast.parse(open(os.path.join(AWX, s)).read())
        numeric = any(isinstance(n, (ast.Import, ast.ImportFrom)) and
                      any(m.split('.')[0] in local | {'math', 'numpy', 'scipy'}
                          for m in ([a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or '']))
                      for n in ast.walk(t))
        first_chain, installed = None, None
        for i, n in enumerate(t.body):
            if isinstance(n, ast.If) and 'detmath.install()' in ast.unparse(n) and '__main__' in ast.unparse(n.test):
                installed = i if installed is None else installed
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or '']
                if any(m.split('.')[0] in local - {'detmath'} for m in mods) and first_chain is None:
                    first_chain = i
            if isinstance(n, ast.If) and installed is None and first_chain is None and any(
                    isinstance(x, (ast.Import, ast.ImportFrom)) for x in ast.walk(n)):
                first_chain = i                     # a guarded import of the chain (whole_audit)
        if not numeric:
            check(True, f'{s}: computes nothing (no math, numpy, scipy or chain import)')
            continue
        check(installed is not None and (first_chain is None or installed < first_chain),
              f'{s}: installs detmath (statement {installed}) before the chain (statement {first_chain})')

    print('5. no float raised to a power in the chain\'s modules')
    seen, todo = set(), sorted(s[:-3] for s in scripts)
    while todo:
        m = todo.pop()
        if m in seen or m not in local:
            continue
        seen.add(m)
        t = ast.parse(open(os.path.join(AWX, m + '.py')).read())
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                todo += [a.name.split('.')[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                todo.append(n.module.split('.')[0])
    bad = []
    for m in sorted(seen - {'detmath'}):
        src = open(os.path.join(AWX, m + '.py')).read()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow) and not (
                    isinstance(n.left, ast.Constant) and isinstance(n.left.value, int)):
                bad.append(f'{m}.py:{n.lineno}: {ast.get_source_segment(src, n)}')
    check(len(seen) > 15, f'the chain loads {len(seen)} awx modules')
    check(not bad, 'no x ** y on a float' + ('' if not bad else ': ' + '; '.join(bad[:6])))

    print('6. an LP\'s answer is its model\'s')
    from scipy.optimize import linprog
    # max x0 + x1 on x0 + x1 <= 1: an edge of optima, whose point the algorithm picks; with the tie-break, one point
    n = 2
    c = np.array([-1.0, -1.0]) + detmath.lp_tie_break(n)
    A = np.array([[1.0, 1.0]]); b = np.array([1.0])
    xs = [detmath.lp_round(linprog(c, A_ub=A, b_ub=b, bounds=[(0, 1)] * n, method=m_).x) for m_ in ('highs-ipm', 'highs-ds')]
    check(np.array_equal(xs[0], xs[1]) and sorted(xs[0].tolist()) == [0.0, 1.0],
          f'the interior point and the simplex give one vertex of the edge: {xs[0].tolist()} / {xs[1].tolist()}')
    q = detmath.lp_round(np.array([0.1, 1 / 3, -2.7, 1e-12]))
    check(np.array_equal(q, detmath.lp_round(q + np.array([1e-15, -1e-16, 2e-15, 0.0]))), 'lp_round takes the last bits off')
    check(all(float(v) * 2 ** 24 == round(float(v) * 2 ** 24) for v in q), 'lp_round lands on its binary grid')

    print(f'\n{"FAILED: " + str(len(FAIL)) if FAIL else "all passed"}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
