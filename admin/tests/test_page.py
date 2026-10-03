"""A cheap guard for the page: no JS parser is in the stack, so every inline <script> of index.html is scanned for
balanced (), [] and {} (strings, template literals, comments and regex literals skipped). A missing `)` blanked the
whole page once (2026-10-03); a real browser run is in the preview check, this catches that class of slip.
"""
import os
import re

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "index.html")
PAIRS = {")": "(", "]": "[", "}": "{"}


def balance_error(src):
    """None when the brackets balance, else a message with the line"""
    stack, i, n, line, prev = [], 0, len(src), 1, ""
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n - 2 if end < 0 else end
            line += src.count("\n", i, end)
            i = end + 2
            continue
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    if c != "`":
                        return "line %d: unterminated string" % line
                    line += 1
                j += 1
            i = j + 1
            prev = "x"
            continue
        if c == "/" and prev in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";"):
            j, in_class = i + 1, False
            while j < n and (src[j] != "/" or in_class) and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                j += 1
            i = j + 1
            prev = "x"
            continue
        if c in "([{":
            stack.append((c, line))
        elif c in ")]}":
            if not stack or stack[-1][0] != PAIRS[c]:
                return "line %d: unexpected %s" % (line, c)
            stack.pop()
        if not c.isspace():
            prev = c
        i += 1
    return "unclosed %s from line %d" % stack[-1] if stack else None


def test_balance_checker_sees_a_missing_paren():
    assert balance_error('f(a, g("x)", /[)]/.test(b))); // )\n') is None
    assert balance_error("f(a, [1, 2);") is not None
    assert balance_error("function f() {\n  g(1;\n}") is not None


def test_every_inline_script_is_balanced():
    with open(PAGE, encoding="utf-8") as f:
        page = f.read()
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page, re.S)
    assert scripts, "no inline script found"
    for k, code in enumerate(scripts, 1):
        assert balance_error(code) is None, "script %d: %s" % (k, balance_error(code))
