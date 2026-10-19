"""Static code-quality audit of the project:  python tools/code_audit.py [--json]

Measures (with the standard library's ``ast`` / ``tokenize``; unused imports come
from ``pyflakes`` when it is installed):

* long functions (> 60 lines flagged, > 100 high) and very large classes,
* bare ``except:`` and silently swallowed ``except Exception: pass``,
* public functions / classes / modules without a docstring,
* public functions without any type hints,
* magic numbers (the same literal used 3+ times inside functions of one file),
* duplicated function bodies across files,
* mixed quote style, mixed line endings, trailing whitespace, very long lines,
* unused imports / variables (pyflakes).

The report is plain data so the same numbers can be shown before and after a
refactoring (see ``quality_audit_before.md`` / ``quality_audit_after.md``).
"""

import ast
import collections
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", ".git", "data", "models", "screenshots_redesign", "docs", "tools", "tests", ".pytest_cache"}
LONG_FUNCTION = 60
VERY_LONG_FUNCTION = 100
BIG_CLASS_METHODS = 30
LONG_LINE = 120
MAGIC_REPEATS = 3
IGNORED_NUMBERS = {0, 1, 2, -1, 0.0, 1.0, 0.5, 100, 10}
DUPLICATE_MIN_LINES = 6


def python_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _is_public(name):
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__") and name == "__init__")


def _needs_docstring(name):
    """Public names need one -- except ``__init__`` (the class docstring covers it), Qt overrides
    (``run``, ``paintEvent``...) and ``forward`` (documented by the framework)."""
    return _is_public(name) and name != "__init__" and name not in ("run", "forward") and not name.endswith("Event")


def _has_hints(node):
    args = node.args.args + node.args.kwonlyargs
    args = [a for a in args if a.arg not in ("self", "cls")]
    return node.returns is not None or any(a.annotation is not None for a in args)


def _is_broad(handler):
    """``except Exception`` / ``BaseException`` -- narrow ones (ImportError, ValueError...) are control flow."""
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names)


def _swallows(handler):
    body = handler.body
    return len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue)) or (
        len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant))


def audit_file(path, source, tree, report, bodies):
    name = rel(path)
    lines = source.split("\n")
    report["loc"] += len(lines)
    if not ast.get_docstring(tree) and len(lines) > 5:
        report["missing_docstrings"].append((name, 1, "module"))
    magic = collections.Counter()
    nested = {id(child) for outer in ast.walk(tree) if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef))
              for child in ast.walk(outer) if child is not outer and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            if length > LONG_FUNCTION:
                report["long_functions"].append((name, node.lineno, node.name, length))
            if (_needs_docstring(node.name) and id(node) not in nested and not node.name.startswith("test")
                    and not ast.get_docstring(node)):
                report["missing_docstrings"].append((name, node.lineno, node.name))
            if _is_public(node.name) and node.name != "__init__" and not _has_hints(node):
                report["missing_hints"].append((name, node.lineno, node.name))
            if length >= DUPLICATE_MIN_LINES:
                dump = ast.dump(ast.Module(body=[n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))], type_ignores=[]))
                bodies[hashlib.md5(dump.encode()).hexdigest()].append((name, node.lineno, node.name, length))
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) and not isinstance(child.value, bool):
                    if child.value not in IGNORED_NUMBERS:
                        magic[child.value] += 1
        elif isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if len(methods) > BIG_CLASS_METHODS:
                report["big_classes"].append((name, node.lineno, node.name, len(methods), node.end_lineno - node.lineno + 1))
            if _is_public(node.name) and not ast.get_docstring(node):
                report["missing_docstrings"].append((name, node.lineno, node.name))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                report["bare_except"].append((name, node.lineno))
            elif _swallows(node) and _is_broad(node):
                report["silent_except"].append((name, node.lineno))
    for value, count in magic.items():
        if count >= MAGIC_REPEATS:
            report["magic_numbers"].append((name, value, count))
    for number, line in enumerate(lines, 1):
        if len(line) > LONG_LINE:
            report["long_lines"].append((name, number, len(line)))
        if line.rstrip() != line and line.strip():
            report["trailing_whitespace"].append((name, number))


def quote_styles(path, source):
    single = double = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                body = token.string.lstrip("rbfuRBFU")
                if body.startswith(('"""', "'''")):
                    continue
                if body.startswith("'"):
                    single += 1
                elif body.startswith('"'):
                    double += 1
    except (tokenize.TokenError, IndentationError):
        pass
    return single, double


def run_pyflakes():
    try:
        result = subprocess.run([sys.executable, "-m", "pyflakes"] + [p for p in python_files()], capture_output=True, text=True, cwd=ROOT)
    except OSError:
        return None
    if "No module named pyflakes" in result.stderr:
        return None
    found = []
    sources = {}

    def intentionally_ignored(path, number):
        """A ``# noqa`` comment on the line marks an import that is deliberate."""
        if path not in sources:
            with open(path, encoding="utf-8", errors="replace") as handle:
                sources[path] = handle.read().split("\n")
        lines = sources[path]
        return 0 < number <= len(lines) and "noqa" in lines[number - 1]

    pattern = re.compile(r"^(.+?\.py):(\d+):(?:\d+:?)? (.*)$")      # a Windows path contains ':' too
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match and not intentionally_ignored(match.group(1), int(match.group(2))):
            found.append((rel(match.group(1)), int(match.group(2)), match.group(3).strip()))
    return found


def build_report():
    report = collections.defaultdict(list)
    for key in ("long_functions", "big_classes", "bare_except", "silent_except", "missing_docstrings", "missing_hints",
                "magic_numbers", "long_lines", "trailing_whitespace", "syntax_errors"):
        report[key] = []
    report["files"] = 0
    report["loc"] = 0
    bodies = collections.defaultdict(list)
    crlf_files, lf_files, mixed_files, quote_report = [], [], [], []
    for path in python_files():
        with open(path, "rb") as handle:
            raw = handle.read()
        source = raw.decode("utf-8", errors="replace")
        report["files"] += 1
        has_crlf, has_lf = b"\r\n" in raw, b"\n" in raw.replace(b"\r\n", b"")
        (mixed_files if has_crlf and has_lf else crlf_files if has_crlf else lf_files).append(rel(path))
        source = source.replace("\r\n", "\n")
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            report["syntax_errors"].append((rel(path), str(error)))
            continue
        audit_file(path, source, tree, report, bodies)
        single, double = quote_styles(path, source)
        if single and double and min(single, double) / (single + double) > 0.10:
            quote_report.append((rel(path), single, double))
    report["duplicates"] = [group for group in bodies.values() if len({g[0] + ":" + g[2] for g in group}) > 1]
    report["line_endings"] = {"crlf": len(crlf_files), "lf": len(lf_files), "mixed": mixed_files}
    report["mixed_quotes"] = quote_report
    report["pyflakes"] = run_pyflakes()
    return dict(report)


def summary_lines(report):
    flakes = report["pyflakes"]
    unused_imports = [f for f in flakes or [] if "imported but unused" in f[2]]
    other_flakes = [f for f in flakes or [] if "imported but unused" not in f[2]]
    rows = [
        ("files scanned", report["files"]),
        ("lines of code", report["loc"]),
        ("functions > %d lines" % LONG_FUNCTION, len(report["long_functions"])),
        ("functions > %d lines (high)" % VERY_LONG_FUNCTION, sum(1 for f in report["long_functions"] if f[3] > VERY_LONG_FUNCTION)),
        ("classes with > %d methods" % BIG_CLASS_METHODS, len(report["big_classes"])),
        ("bare except:", len(report["bare_except"])),
        ("silently swallowed exceptions", len(report["silent_except"])),
        ("public items without docstring", len(report["missing_docstrings"])),
        ("public functions without type hints", len(report["missing_hints"])),
        ("magic numbers (same literal %d+ times in a file)" % MAGIC_REPEATS, len(report["magic_numbers"])),
        ("duplicated function bodies (across files)", len(report["duplicates"])),
        ("files with mixed quote style (>10% minority)", len(report["mixed_quotes"])),
        ("files with mixed line endings", len(report["line_endings"]["mixed"])),
        ("lines with trailing whitespace", len(report["trailing_whitespace"])),
        ("lines longer than %d" % LONG_LINE, len(report["long_lines"])),
        ("unused imports (pyflakes)", len(unused_imports) if flakes is not None else "n/a"),
        ("other pyflakes warnings", len(other_flakes) if flakes is not None else "n/a"),
    ]
    return rows


def main():
    report = build_report()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=1, default=str))
        return 0
    width = max(len(str(label)) for label, _ in summary_lines(report))
    for label, value in summary_lines(report):
        print("%-*s  %s" % (width, label, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())
