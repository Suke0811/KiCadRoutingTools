#!/usr/bin/env python3
"""The plugin never uses a wxPython stock GDI object (#1080).

wx.WHITE, wx.TRANSPARENT_PEN, wx.NORMAL_FONT and the rest are initialised
only when PYTHON creates the wx.App. Inside KiCad the app is KiCad's, so
there they stay invalid: the About tab's Donate button drew its label black
and its heart not at all. Every headless gate creates its own wx.App before
building a dialog, so none of them can see it -- this static scan can.

STOCK is the list KiCad's bundled wxPython reports as not IsOk() before any
wx.App exists (the Null* objects, invalid by design, excluded):

    import wx
    kinds = (wx.Colour, wx.Pen, wx.Brush, wx.Font, wx.Cursor)
    [n for n in dir(wx) if not n.startswith('Null')
     and isinstance(getattr(wx, n), kinds) and not getattr(wx, n).IsOk()]

    python3 tests/test_1080_no_wx_stock_objects.py
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, 'kicad_routing_plugin')

STOCK = frozenset([
    'BLACK', 'BLACK_BRUSH', 'BLACK_DASHED_PEN', 'BLACK_PEN', 'BLUE',
    'BLUE_BRUSH', 'BLUE_PEN', 'CROSS_CURSOR', 'CYAN', 'CYAN_BRUSH',
    'CYAN_PEN', 'GREEN', 'GREEN_BRUSH', 'GREEN_PEN', 'GREY_BRUSH', 'GREY_PEN',
    'HOURGLASS_CURSOR', 'ITALIC_FONT', 'LIGHT_GREY', 'LIGHT_GREY_BRUSH',
    'LIGHT_GREY_PEN', 'MEDIUM_GREY_BRUSH', 'MEDIUM_GREY_PEN', 'NORMAL_FONT',
    'RED', 'RED_BRUSH', 'RED_PEN', 'SMALL_FONT', 'STANDARD_CURSOR',
    'SWISS_FONT', 'TRANSPARENT_BRUSH', 'TRANSPARENT_PEN', 'WHITE',
    'WHITE_BRUSH', 'WHITE_PEN', 'YELLOW', 'YELLOW_BRUSH', 'YELLOW_PEN',
])


def stock_uses(source, filename='<src>'):
    """(line, name) for every `wx.<stock>` attribute in the source."""
    hits = []
    for node in ast.walk(ast.parse(source, filename)):
        if (isinstance(node, ast.Attribute) and node.attr in STOCK
                and isinstance(node.value, ast.Name) and node.value.id == 'wx'):
            hits.append((node.lineno, node.attr))
    return hits


def main():
    # The scanner must see a planted use, or an empty result proves nothing.
    planted = stock_uses("gc.SetFont(font, wx.WHITE)\ngc.SetPen(wx.TRANSPARENT_PEN)\n")
    if planted != [(1, 'WHITE'), (2, 'TRANSPARENT_PEN')]:
        print(f"BROKEN TEST: scanner missed planted stock objects: {planted}")
        return 1

    files, failures = 0, []
    for root, _dirs, names in os.walk(PLUGIN):
        for name in sorted(names):
            if not name.endswith('.py'):
                continue
            path = os.path.join(root, name)
            with open(path, encoding='utf-8') as f:
                src = f.read()
            files += 1
            for line, attr in stock_uses(src, path):
                failures.append(f"{os.path.relpath(path, REPO)}:{line}: wx.{attr}")
    if files == 0:
        print(f"BROKEN TEST: no .py files under {PLUGIN}")
        return 1
    if failures:
        print("FAIL: wx stock objects are invalid inside KiCad; build the "
              "colour/pen/brush/font explicitly instead:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"ALL PASS ({files} plugin files, no wx stock objects)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
