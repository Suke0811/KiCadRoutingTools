"""detmath -- the same bits on every machine. A Mac (Apple's libm, Accelerate) and a Linux box (glibc, OpenBLAS) round
the transcendental functions (sin, cos, atan2, exp, log, pow -- math's and numpy's alike), np.hypot, long dot products
and HiGHS's own arithmetic differently in the last bit, and the whole route turns one such bit into another plan: a
lane's tie decided the other way, an LP landing on another of its equal optima (K28: the geometry LP's input identical
on both, its answer 10 mm apart).

The functions here are fdlibm's algorithms and coefficients (the ones Java's StrictMath uses for the same reason),
from + - * / sqrt alone, which IEEE-754 rounds the same everywhere; within 1-3 ulp of the platform's. The LP helpers
make a solution a function of the model alone: lp_tie_break decides the model's exact ties by a fixed cost per column
(small beside every real cost, large beside the solver's tolerances), and lp_round takes the solver's last bits off.
"""
import math

_fabs, _frexp, _ldexp, _sqrt, _isfinite = math.fabs, math.frexp, math.ldexp, math.sqrt, math.isfinite
NAN, INF = float('nan'), float('inf')

# the platform's own, for arguments past the reduction's range (never a coordinate): kept before install() replaces
# math's, which would otherwise call back into this module
_LIBM = {n_: getattr(math, n_) for n_ in ('sin', 'cos')}

# ---- sin / cos: reduction by pi/2 as a 33-bit head and its tail (exact products for |n| < 2**20), fdlibm kernels
_INVPIO2 = 6.36619772367581382433e-01
_PIO2_1, _PIO2_1T = 1.57079632673412561417e+00, 6.07710050650619224932e-11
_S1, _S2, _S3 = -1.66666666666666324348e-01, 8.33333333332248946124e-03, -1.98412698298579493134e-04
_S4, _S5, _S6 = 2.75573137070700676789e-06, -2.50507602534068634195e-08, 1.58969099521155010221e-10
_C1, _C2, _C3 = 4.16666666666666019037e-02, -1.38888888888741095749e-03, 2.48015872894767294178e-05
_C4, _C5, _C6 = -2.75573143513906633035e-07, 2.08757232129817482790e-09, -1.13596475577881948265e-11


def _ksin(x, y):
    z = x * x; v = z * x
    r = _S2 + z * (_S3 + z * (_S4 + z * (_S5 + z * _S6)))
    return x - ((z * (0.5 * y - v * r) - y) - v * _S1)


def _kcos(x, y):
    z = x * x; w = z * z
    r = z * (_C1 + z * (_C2 + z * _C3)) + w * w * (_C4 + z * (_C5 + z * _C6))
    hz = 0.5 * z; w = 1.0 - hz
    return w + (((1.0 - w) - hz) + (z * r - x * y))


def _rem(x):
    n = round(x * _INVPIO2)
    fn = float(n)
    r = x - fn * _PIO2_1
    w = fn * _PIO2_1T
    y0 = r - w
    return n & 3, y0, (r - y0) - w


def sin(x):
    x = float(x)
    if not _isfinite(x) or _fabs(x) > 1e5:
        return _LIBM['sin'](x) if x == x and _fabs(x) != INF else NAN
    q, a, b = _rem(x)
    return (_ksin(a, b), _kcos(a, b), -_ksin(a, b), -_kcos(a, b))[q]


def cos(x):
    x = float(x)
    if not _isfinite(x) or _fabs(x) > 1e5:
        return _LIBM['cos'](x) if x == x and _fabs(x) != INF else NAN
    q, a, b = _rem(x)
    return (_kcos(a, b), -_ksin(a, b), -_kcos(a, b), _ksin(a, b))[q]


def tan(x):
    return sin(x) / cos(x)


# ---- atan / atan2 (fdlibm s_atan.c, e_atan2.c)
_ATANHI = (4.63647609000806093515e-01, 7.85398163397448278999e-01, 9.82793723247329054082e-01, 1.57079632679489655800e+00)
_ATANLO = (2.26987774529616870924e-17, 3.06161699786838301793e-17, 1.39033110312309984516e-17, 6.12323399573676603587e-17)
_AT = (3.33333333333329318027e-01, -1.99999999998764832476e-01, 1.42857142725034663711e-01, -1.11111104054623557880e-01,
       9.09088713343650656196e-02, -7.69187620504482999495e-02, 6.66107313738753120669e-02, -5.83357013379057348645e-02,
       4.97687799461593236017e-02, -3.65315727442169155270e-02, 1.62858201153657823623e-02)
PI, PI_LO, PIO2 = 3.1415926535897931160e+00, 1.2246467991473531772e-16, 1.5707963267948965580e+00


def atan(x):
    x = float(x)
    if x != x:
        return x
    neg = x < 0 or (x == 0 and math.copysign(1.0, x) < 0)
    t = _fabs(x)
    if t >= 7.378697629483821e19:                      # 2**66
        return -(_ATANHI[3] + _ATANLO[3]) if neg else _ATANHI[3] + _ATANLO[3]
    if t < 0.4375:
        if t < 3.725290298461914e-09:                  # 2**-28
            return x
        i = -1
    elif t < 1.1875:
        if t < 0.6875:
            i = 0; t = (2.0 * t - 1.0) / (2.0 + t)
        else:
            i = 1; t = (t - 1.0) / (t + 1.0)
    elif t < 2.4375:
        i = 2; t = (t - 1.5) / (1.0 + 1.5 * t)
    else:
        i = 3; t = -1.0 / t
    z = t * t; w = z * z
    s1 = z * (_AT[0] + w * (_AT[2] + w * (_AT[4] + w * (_AT[6] + w * (_AT[8] + w * _AT[10])))))
    s2 = w * (_AT[1] + w * (_AT[3] + w * (_AT[5] + w * (_AT[7] + w * _AT[9]))))
    if i < 0:
        return x - x * (s1 + s2)
    z = _ATANHI[i] - ((t * (s1 + s2) - _ATANLO[i]) - t)
    return -z if neg else z


def atan2(y, x):
    y, x = float(y), float(x)
    if x != x or y != y:
        return x + y
    if x == 1.0:
        return atan(y)
    m = (1 if math.copysign(1.0, y) < 0 else 0) | (2 if math.copysign(1.0, x) < 0 else 0)
    if y == 0:
        return (y, y, PI, -PI)[m]
    if x == 0:
        return -PIO2 if y < 0 else PIO2
    if x == INF or x == -INF:
        if y == INF or y == -INF:
            return (0.25 * PI, -0.25 * PI, 0.75 * PI, -0.75 * PI)[m]
        return (0.0, -0.0, PI, -PI)[m]
    if y == INF or y == -INF:
        return -PIO2 if y < 0 else PIO2
    k = _frexp(y)[1] - _frexp(x)[1]
    if k > 60:
        z = PIO2 + 0.5 * PI_LO
    elif x < 0 and k < -60:
        z = 0.0
    else:
        z = atan(_fabs(y / x))
    if m == 0:
        return z
    if m == 1:
        return -z
    if m == 2:
        return PI - (z - PI_LO)
    return (z - PI_LO) - PI


def asin(x):
    x = float(x)
    if _fabs(x) > 1:
        raise ValueError('math domain error')
    return atan2(x, _sqrt((1.0 - x) * (1.0 + x)))


def acos(x):
    x = float(x)
    if _fabs(x) > 1:
        raise ValueError('math domain error')
    return atan2(_sqrt((1.0 - x) * (1.0 + x)), x)


# ---- exp / log (fdlibm e_exp.c, e_log.c)
_LN2HI, _LN2LO, _INVLN2 = 6.93147180369123816490e-01, 1.90821492927058770002e-10, 1.44269504088896338700e+00
_P1, _P2, _P3 = 1.66666666666666019037e-01, -2.77777777770155933842e-03, 6.61375632143793436117e-05
_P4, _P5 = -1.65339022054652515390e-06, 4.13813679705723846039e-08


def exp(x):
    x = float(x)
    if x != x:
        return x
    if x > 709.782712893383973096:
        raise OverflowError('math range error')
    if x < -745.13321910194110842:
        return 0.0
    t = _fabs(x)
    if t > 0.5 * 0.6931471805599453:
        if t < 1.5 * 0.6931471805599453:
            k = 1 if x > 0 else -1
            hi = x - k * _LN2HI; lo = k * _LN2LO
        else:
            k = int(_INVLN2 * x + (0.5 if x > 0 else -0.5))
            hi = x - k * _LN2HI; lo = k * _LN2LO
        x = hi - lo
    elif t < 3.725290298461914e-09:
        return 1.0 + x
    else:
        k = 0; hi = lo = 0.0
    t = x * x
    c = x - t * (_P1 + t * (_P2 + t * (_P3 + t * (_P4 + t * _P5))))
    if k == 0:
        return 1.0 - ((x * c) / (c - 2.0) - x)
    y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi)
    return _ldexp(y, k)


_LG = (6.666666666666735130e-01, 3.999999999940941908e-01, 2.857142874366239149e-01, 2.222219843214978396e-01,
       1.818357216161805012e-01, 1.531383769920937332e-01, 1.479819860511658591e-01)
_SQRT2H = 0.7071067811865476


def log(x, base=None):
    if base is not None:
        return log(x) / log(base)
    x = float(x)
    if x != x or x == INF:
        return x
    if x <= 0:
        raise ValueError('math domain error')
    m, e = _frexp(x)                                    # x = m * 2**e, m in [0.5, 1)
    if m < _SQRT2H:
        m *= 2.0; e -= 1
    f = m - 1.0
    dk = float(e)
    s = f / (2.0 + f); z = s * s; w = z * z
    t1 = w * (_LG[1] + w * (_LG[3] + w * _LG[5]))
    t2 = z * (_LG[0] + w * (_LG[2] + w * (_LG[4] + w * _LG[6])))
    R = t2 + t1
    hfsq = 0.5 * f * f
    return dk * _LN2HI - ((hfsq - (s * (hfsq + R) + dk * _LN2LO)) - f)


_LN10 = 2.302585092994045684
def log10(x):
    return log(x) / _LN10


def pow(x, y):
    x, y = float(x), float(y)
    if y == 2.0:
        return x * x
    if y == 0.5 and x >= 0:
        return _sqrt(x)
    if y == 1.0:
        return x
    if y == 0.0:
        return 1.0
    if y == int(y) and _fabs(y) <= 64:                  # a small integer power: squaring, one fixed order
        n = int(_fabs(y)); r = 1.0; b = x
        while n:
            if n & 1:
                r *= b
            b *= b; n >>= 1
        return 1.0 / r if y < 0 else r
    if x < 0:
        raise ValueError('math domain error')
    if x == 0:
        return 0.0 if y > 0 else INF
    return exp(y * log(x))


# ---- linear programs: one answer per model, whatever the solver's rounding
LP_TIE = 1e-4           # per unit of a column: below any real cost's step, above HiGHS's 1e-7 tolerances
LP_QUANT = 2.0 ** -24   # a solution rounded to this: ~6e-8 (mm), exact in binary, far below any geometry


def lp_tie_break(n):
    """a fixed cost per column (LP_TIE times 0.5 .. 1.5, the golden-ratio sequence): with it, the LP's optimum is one
    point, not a face whose vertex the solver's rounding picks"""
    import numpy as np
    return LP_TIE * (0.5 + (np.arange(1, n + 1, dtype=float) * 0.6180339887498949) % 1.0)


def lp_round(x):
    """the solution without the solver's last bits (a power-of-two grid: the scaling is exact)"""
    import numpy as np
    return np.round(np.asarray(x, float) / LP_QUANT) * LP_QUANT


# ---- the swap: a chain stage's process computes with these
MATH_FUNCS = ('sin', 'cos', 'tan', 'atan', 'atan2', 'asin', 'acos', 'exp', 'log', 'log10', 'pow')
_ORIG = {}


def installed():
    """True in a process that computes with this module's functions (a chain stage)"""
    return bool(_ORIG)


def _file_tag():
    import hashlib
    with open(__file__, 'rb') as f:
        return '#det' + hashlib.sha1(f.read()).hexdigest()[:8]


MEMO_TAG = _file_tag()
"""what a cache adds to its key for a value computed after install(): a value from the platform's functions, or from
another version of these, is another value"""


def install():
    """Put this module's functions in place of math's and numpy's, for this process: what every chain stage run as a
    script does first, before it imports the chain (whose modules compute constants as they load). Idempotent.
    math.hypot / math.dist / math.sqrt and numpy's arithmetic, sums and small products stay: they give the same bits
    everywhere already. What it cannot reach: `x ** y` on floats (the C library's pow -- the chain writes x * x) and
    compiled code (HiGHS: lp_tie_break / lp_round)."""
    if _ORIG:
        return
    import numpy as np
    for n in MATH_FUNCS:
        _ORIG['math.' + n] = getattr(math, n)
        setattr(math, n, globals()[n])
    for n, f in (('hypot', np_hypot), ('interp', np_interp), ('sin', _np1(sin)), ('cos', _np1(cos)), ('tan', _np1(tan)),
                 ('arctan', _np1(atan)), ('arcsin', _np1(asin)), ('arccos', _np1(acos)), ('exp', _np1(exp)),
                 ('log', _np1(log)), ('arctan2', _np2(atan2)), ('power', _np2(pow))):
        _ORIG['np.' + n] = getattr(np, n)
        setattr(np, n, f)


def np_hypot(a, b):
    """sqrt(a*a + b*b), elementwise: three operations IEEE rounds the same everywhere (libm's hypot does not)"""
    import numpy as np
    a = np.asarray(a, float); b = np.asarray(b, float)
    r = np.sqrt(a * a + b * b)
    return r if r.ndim else np.float64(r)


def np_interp(x, xp, fp, left=None, right=None, period=None):
    """np.interp's contract (increasing xp; left / right past the ends) from + - * / alone"""
    import numpy as np
    assert period is None, 'np_interp: no period'
    xp = np.asarray(xp, float); fp = np.asarray(fp, float); xa = np.asarray(x, float)
    lo = fp[0] if left is None else left
    hi = fp[-1] if right is None else right
    if len(xp) > 1:
        j = np.clip(np.searchsorted(xp, xa, side='right') - 1, 0, len(xp) - 2)
        dx = xp[j + 1] - xp[j]
        sl = (fp[j + 1] - fp[j]) / np.where(dx != 0, dx, 1.0)
        y = np.where((xa == xp[j]) | (dx == 0), fp[j], sl * (xa - xp[j]) + fp[j])
    else:
        y = np.full(xa.shape, fp[0])
    y = np.where(xa == xp[-1], fp[-1], y)
    y = np.where(xa < xp[0], lo, np.where(xa > xp[-1], hi, y))
    return y if y.ndim else np.float64(y)


def _np1(f):
    """a scalar function of this module over an array, element by element (the chain calls these on a few hundred
    elements in a run; np.hypot, called on a billion, is vectorised above)"""
    def g(x):
        import numpy as np
        a = np.asarray(x, float)
        r = np.array([f(v) for v in a.ravel().tolist()], float).reshape(a.shape)
        return r if r.ndim else np.float64(r)
    return g


def _np2(f):
    def g(x, y):
        import numpy as np
        a, b = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
        r = np.array([f(u, v) for u, v in zip(a.ravel().tolist(), b.ravel().tolist())], float).reshape(a.shape)
        return r if r.ndim else np.float64(r)
    return g
