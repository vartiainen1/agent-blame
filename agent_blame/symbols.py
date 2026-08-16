"""Symbol / caller analysis (Phase 2C): conservative, AST-based for Python.

Language-agnostic shape (spec section 3): detect language -> extract
symbols -> find references -> classify relationships. First-class language:
Python, using only the stdlib `ast` module (source is PARSED, never
executed). Unsupported languages produce no symbol analysis - honest
absence, documented in the README, never a regex-based guess presented as
an AST-level result.

Relationship honesty rules (spec section 1/7/13):

    DIRECT_CALL      bare/aliased call resolved to the target symbol via
                     same-module scope or a resolved from-import
    ATTRIBUTE_CALL   module.attr() / Class.method() where the module or
                     class resolves to the target's module
    IMPORT_REFERENCE the target symbol (or its module) is imported
    POSSIBLE_CALL    the name matches but resolution is ambiguous (no
                     import, star import, unknown receiver type)
    TEXTUAL_MATCH    the name appears as text only (strings/comments/other
                     identifiers) - ZERO evidence weight
    UNRESOLVED       dynamic patterns (getattr/eval/reflection) - ZERO
                     weight

Only DIRECT_CALL / ATTRIBUTE_CALL / IMPORT_REFERENCE / POSSIBLE_CALL enter
the evidence engine. TEXTUAL_MATCH and UNRESOLVED are reported for
transparency and can never move confidence or risk. A confirmed caller
always outweighs any number of textual matches.

Conservatism rules (spec section 1/17):
  - a local definition of the same name shadows a cross-module reference
    (a module that defines its own `authenticate` never credits ours)
  - ambiguous imports (star imports, relative imports, two modules with
    the same file stem) downgrade to POSSIBLE, never DIRECT
  - comments, strings and unrelated identifiers (e.g. `authenticate_other`)
    never produce a caller - only a zero-weight TEXTUAL_MATCH report

Performance: the whole repository's Python sources at one revision are
fetched with exactly TWO git calls (`git ls-tree -r -z` for the file list
plus ONE `git cat-file --batch` streaming every blob) and memoized in the
AnalysisMemo for the run. Per-file AST work is lazy and cached per
(revision, path); a cheap word-boundary regex pre-filter skips files that
cannot contain a reference.

Security: source is untrusted input. ast.parse() does not execute code;
malformed source is caught (SyntaxError) and the file is skipped.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional, Tuple

from .git import git_output
from .graph import _is_test_path
from .models import CallerRef, Symbol, Target
from .ranking import weight_for
from .repository import Repository

# Relationship types (stable, machine-readable).
DIRECT_CALL = "DIRECT_CALL"
ATTRIBUTE_CALL = "ATTRIBUTE_CALL"
IMPORT_REFERENCE = "IMPORT_REFERENCE"
POSSIBLE_CALL = "POSSIBLE_CALL"
TEXTUAL_MATCH = "TEXTUAL_MATCH"
UNRESOLVED = "UNRESOLVED"

_WORD_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")

# Defensive cap for the whole-repo in-memory source index: refuse to scan
# repositories with a pathological number of Python files (never load a
# hostile repository into memory unbounded). Real codebases the tool is
# meant for are far below this.
_MAX_INDEX_FILES = 20000


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(path: str) -> Optional[str]:
    """Detect the language of a source file from its extension.

    Returns None for unsupported languages (no symbol analysis). Python is
    the first-class implementation (stdlib AST). Nothing else is claimed.
    """
    if path.endswith(".py"):
        return "python"
    return None


# ---------------------------------------------------------------------------
# Repository source index (2 git calls per revision, memoized)
# ---------------------------------------------------------------------------

def _ls_tree_py_files(repo: Repository, revision: str) -> Dict[str, str]:
    """Map path -> blob sha for every .py file at `revision` (one git call)."""
    raw = git_output(["ls-tree", "-r", "-z", revision], cwd=repo.root)
    out: Dict[str, str] = {}
    for entry in raw.split("\x00"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        if not path or not path.endswith(".py"):
            continue
        parts = meta.split(" ")
        if len(parts) == 3 and parts[1] == "blob":
            out[path] = parts[2]
    return out


def _cat_file_batch(repo: Repository, shas: List[str]) -> Dict[str, str]:
    """Fetch blob contents in ONE git process (`git cat-file --batch`).

    Each request line produces `<sha> blob <size>\\n<content>\\n` (or
    `<sha> missing\\n`). Parsing is structural (read exactly `size` bytes),
    so blob content can never be mistaken for framing. Content is decoded
    with errors='replace' - source is untrusted input.
    """
    if not shas:
        return {}
    from .git import git_bytes
    payload = "".join(f"{s}\n" for s in shas).encode("utf-8")
    data = git_bytes(["cat-file", "--batch"], input_bytes=payload,
                     cwd=repo.root)
    out: Dict[str, str] = {}
    i, n = 0, len(data)
    while i < n:
        j = data.find(b"\n", i)
        if j == -1:
            break
        header = data[i:j]
        i = j + 1
        parts = header.split(b" ")
        if len(parts) == 3 and parts[1] == b"blob":
            try:
                size = int(parts[2])
            except ValueError:
                continue
            content = data[i:i + size]
            out[parts[0].decode("ascii", errors="replace")] = \
                content.decode("utf-8", errors="replace")
            i += size
            if i < n and data[i:i + 1] == b"\n":
                i += 1
        # "<sha> missing" - skip silently.
    return out


def load_py_sources(repo: Repository, revision: str) -> Dict[str, str]:
    """All Python source at `revision`, memoized per revision on the memo.

    Exactly two git calls per revision (ls-tree + one cat-file batch).
    Sources are kept for the run only - never persisted.
    """
    files = _ls_tree_py_files(repo, revision)
    if not files:
        return {}
    if len(files) > _MAX_INDEX_FILES:
        return {}
    contents = _cat_file_batch(repo, sorted(files.values()))
    out: Dict[str, str] = {}
    for path, sha in files.items():
        content = contents.get(sha)
        if content is not None:
            out[path] = content
    return out


# ---------------------------------------------------------------------------
# Symbol extraction (stdlib AST - parse only, never execute)
# ---------------------------------------------------------------------------

def extract_symbols(source: str, path: str) -> List[Symbol]:
    """Extract functions/methods/classes from Python source via AST.

    Qualified names: methods are `Class.method`, nested functions are
    `outer.inner`. Malformed source returns [] (never crashes).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    symbols: List[Symbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            _collect_symbol(node, path, symbols, parent_name=None)
    return symbols


def _collect_symbol(node, path: str, symbols: List[Symbol],
                    parent_name: Optional[str]) -> None:
    """Add a symbol and its children, computing qualified names."""
    if isinstance(node, ast.ClassDef):
        name = f"{parent_name}.{node.name}" if parent_name else node.name
        symbols.append(Symbol(path=path, name=name, kind="class",
                              start_line=node.lineno,
                              end_line=_end_line(node), parent=parent_name))
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(Symbol(
                    path=path, name=f"{name}.{child.name}", kind="method",
                    start_line=child.lineno, end_line=_end_line(child),
                    parent=name,
                ))
                # Nested functions inside methods (rare; keep qualified).
                _collect_nested(child, path, symbols, f"{name}.{child.name}")
    else:
        name = f"{parent_name}.{node.name}" if parent_name else node.name
        kind = "function"
        symbols.append(Symbol(path=path, name=name, kind=kind,
                              start_line=node.lineno, end_line=_end_line(node),
                              parent=parent_name))
        _collect_nested(node, path, symbols, name)


def _collect_nested(node, path: str, symbols: List[Symbol],
                    qualname: str) -> None:
    """Nested function definitions inside a function body."""
    for child in getattr(node, "body", []):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol(
                path=path, name=f"{qualname}.{child.name}", kind="function",
                start_line=child.lineno, end_line=_end_line(child),
                parent=qualname,
            ))
            _collect_nested(child, path, symbols, f"{qualname}.{child.name}")


def _end_line(node) -> int:
    end = getattr(node, "end_lineno", None)
    return end if end is not None else node.lineno


def _innermost_symbol_at(symbols: List[Symbol], line: int) -> Optional[Symbol]:
    """The deepest symbol whose range contains `line`."""
    best = None
    for s in symbols:
        if s.start_line <= line <= s.end_line:
            if best is None or s.start_line > best.start_line:
                best = s
    return best


def enclosing_symbol(repo: Repository, revision: str, target: Target,
                     memo: AnalysisMemo) -> Optional[Symbol]:
    """The symbol containing the target line at `revision`, or None.

    Returns None when the file is not Python, unparseable, or the line is
    not inside any definition (module-level code, data files, ...).
    """
    if detect_language(target.file) != "python":
        return None
    sources = memo.py_sources(repo, revision)
    source = sources.get(target.file)
    if source is None:
        return None
    symbols = memo.file_symbols(revision, target.file, source)
    if not symbols:
        return None
    sym = _innermost_symbol_at(symbols, target.start_line)
    if sym is None and target.end_line != target.start_line:
        sym = _innermost_symbol_at(symbols, target.end_line)
    return sym


# ---------------------------------------------------------------------------
# Import context (conservative module resolution)
# ---------------------------------------------------------------------------

class _ImportCtx:
    """Import facts of one file, for conservative module resolution."""

    def __init__(self) -> None:
        self.modules: Dict[str, str] = {}       # alias -> dotted module
        self.from_imports: Dict[str, Tuple[str, str]] = {}  # name -> (module, orig)
        self.star_modules: set = set()          # modules via `from m import *`
        self.relative = False                   # any relative import seen

    @staticmethod
    def from_tree(tree) -> "_ImportCtx":
        ctx = _ImportCtx()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    ctx.modules[alias.asname or top] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import: package-relative, ambiguous
                    ctx.relative = True
                    continue
                module = node.module or ""
                if any(a.name == "*" for a in node.names):
                    ctx.star_modules.add(module)
                    continue
                for alias in node.names:
                    ctx.from_imports[alias.asname or alias.name] = (
                        module, alias.name)
        return ctx


def _module_matches(module: str, target_module: str, target_stem: str,
                    stem_ambiguous: bool) -> bool:
    """Does an import of `module` refer to the target's module?

    Full dotted match is precise. Stem-level match (module's last
    component == target file stem) is accepted only when no OTHER module
    shares that stem - otherwise the reference is ambiguous and must be
    downgraded, never claimed.
    """
    if module == target_module:
        return True
    if module.rsplit(".", 1)[-1] == target_stem and not stem_ambiguous:
        return True
    return False


def _chain_to_module(chain: List[str], ctx: _ImportCtx) -> Optional[str]:
    """Resolve a receiver chain like `a.b` against imports to a module.

    Handles `import auth`, `import auth as a`, `import src.auth`,
    `import src.auth as sa`. Returns the dotted module or None.
    """
    dotted = ".".join(chain)
    if dotted in ctx.modules and ctx.modules[dotted] == dotted:
        return dotted            # explicit `import a.b.c`
    head = chain[0]
    if head not in ctx.modules:
        return None
    module = ctx.modules[head]
    if module == dotted:
        return module
    rest = chain[1:]
    if rest and module.endswith("." + ".".join(rest)):
        return module            # module already covers the rest
    if rest:
        return module + "." + ".".join(rest)
    return module


# ---------------------------------------------------------------------------
# Caller discovery
# ---------------------------------------------------------------------------

def _call_chain(func) -> Tuple[Optional[List[str]], Optional[str]]:
    """Decompose a call's func into (name_chain, final_name) or (None, None).

    `a.b.c()` -> (["a", "b"], "c"). Returns (None, None) for dynamic
    receivers (getattr(...), subscripts, ...) - those are UNRESOLVED.
    """
    parts: List[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        parts.reverse()
        return parts[:-1], parts[-1]
    return None, None


def discover_callers(repo: Repository, revision: str, symbol: Symbol,
                     memo: AnalysisMemo,
                     change_map: Optional[Dict[str, str]] = None,
                     ) -> List[CallerRef]:
    """Find references to `symbol` across the repository at `revision`.

    Returns classified CallerRef entries, aggregated per (path, caller
    symbol, relationship). TEXTUAL_MATCH entries are aggregated into ONE
    entry carrying the file count so a common name cannot flood output.
    """
    sources = memo.py_sources(repo, revision)
    target_path = symbol.path
    target_name = symbol.name.split(".")[-1]
    target_module = target_path[:-3].replace("/", ".") if target_path.endswith(".py") else ""
    target_stem = target_path.rsplit("/", 1)[-1][:-3] if target_path.endswith(".py") else ""
    stem_ambiguous = any(
        p != target_path and p.endswith(".py")
        and p.rsplit("/", 1)[-1][:-3] == target_stem
        for p in sources)

    refs: List[CallerRef] = []
    textual_files: List[str] = []
    unresolved_refs: int = 0

    for path in sorted(sources):
        content = sources[path]
        if not _name_in_text(content, target_name):
            continue  # cheap pre-filter: name must appear as a whole word

        tree = memo.file_ast(revision, path, content)
        if tree is None:
            continue
        ctx = _ImportCtx.from_tree(tree)
        file_symbols = memo.file_symbols(revision, path, content)
        in_target_file = (path == target_path)
        target_def_here = _has_local_def(file_symbols, target_name)
        found_call = False

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chain, final = _call_chain(node.func)
            if chain is None:
                # dynamic receiver - report as UNRESOLVED (never evidence)
                if _dynamic_reference(node, target_name):
                    unresolved_refs += 1
                continue
            if final != target_name and final not in ctx.from_imports:
                # `from auth import authenticate as af` makes af() a call
                # to OUR symbol; _classify_call resolves the alias via the
                # from_imports map. Any other name is a different symbol.
                continue
            rel, conf = _classify_call(
                node, chain, final, ctx, symbol, in_target_file,
                target_def_here, target_module, target_stem, stem_ambiguous,
                file_symbols)
            if rel is None:
                continue  # reference to a DIFFERENT symbol (e.g. local def)
            if rel == UNRESOLVED:
                unresolved_refs += 1
                continue
            found_call = True
            _add_ref(refs, path, file_symbols, node.lineno, rel, conf,
                     change_map, target_name)

        # Import references: the target symbol or module imported here.
        if path != target_path:
            for name, (mod, orig) in sorted(ctx.from_imports.items()):
                if (orig == target_name and _module_matches(
                        mod, target_module, target_stem, stem_ambiguous)):
                    _add_ref(refs, path, file_symbols, _import_line(tree, name),
                             IMPORT_REFERENCE, "LOW", change_map, target_name)
            for alias in sorted(ctx.modules):
                if _module_matches(ctx.modules[alias], target_module,
                                   target_stem, stem_ambiguous):
                    _add_ref(refs, path, file_symbols, _import_line(tree, alias),
                             IMPORT_REFERENCE, "LOW", change_map, target_name)

        if not found_call and path != target_path:
            if _name_in_text(content, target_name):
                textual_files.append(path)

    if unresolved_refs:
        refs.append(CallerRef(
            symbol=f"<unresolved:{target_name}>", path="", name="<unresolved>",
            line=0, call_sites=unresolved_refs,
            relationship=UNRESOLVED, status="LIVE", confidence="LOW",
            text=(f"{unresolved_refs} dynamic reference(s) to "
                  f"{target_name!r} (getattr/eval/reflection) could not be "
                  f"resolved - static analysis cannot confirm dynamic callers")))

    if textual_files:
        refs.append(CallerRef(
            symbol=f"<textual:{target_name}>", path="", name="<textual>",
            line=0, call_sites=len(textual_files),
            relationship=TEXTUAL_MATCH, status="LIVE", confidence="LOW",
            text=(f"{len(textual_files)} file(s) contain the name "
                  f"{target_name!r} as text only (strings, comments or "
                  f"unrelated identifiers)")))

    return sorted(refs, key=lambda r: (r.relationship, r.path, r.name))


def _has_local_def(symbols: List[Symbol], name: str) -> bool:
    """Does this file DEFINE a symbol with this (unqualified) name?"""
    for s in symbols:
        if s.name == name or s.name.rsplit(".", 1)[-1] == name:
            return True
    return False


def _import_line(tree, name: str) -> int:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == name or alias.name.split(".")[0] == name:
                    return node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return node.lineno
    return 0


def _dynamic_reference(node: ast.Call, target_name: str) -> bool:
    """Is this a dynamic pattern (getattr/eval/...) naming the target?"""
    if isinstance(node.func, ast.Name) and node.func.id in (
            "getattr", "eval", "exec", "globals", "locals", "__import__"):
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value == target_name:
                return True
    return False


def _classify_call(node: ast.Call, receiver_chain: List[str], final: str,
                   ctx: _ImportCtx, symbol: Symbol, in_target_file: bool,
                   target_def_here: bool,
                   target_module: str, target_stem: str,
                   stem_ambiguous: bool,
                   file_symbols: List[Symbol],
                   ) -> Tuple[Optional[str], str]:
    """Classify one call site -> (relationship, confidence) or (None, conf).

    `receiver_chain` is the name chain WITHOUT the final callee name
    ([] for a bare call; ["auth"] for auth.authenticate(); ["Auth"] for
    Auth.check(x)). None means the call is NOT a reference to the target
    symbol (e.g. a local definition of the same name shadows it).
    Deterministic; conservatism wins over recall.
    """
    target_name = symbol.name.split(".")[-1]
    target_kind = symbol.kind
    target_class = symbol.parent

    if not receiver_chain:
        # bare call: authenticate() / check()
        if in_target_file:
            if target_kind == "method":
                if _inside_class(node, symbol, file_symbols):
                    return DIRECT_CALL, "HIGH"
                return POSSIBLE_CALL, "LOW"
            return DIRECT_CALL, "HIGH"
        # bare call in another module
        if target_def_here:
            return None, "LOW"   # this file defines its own: not our symbol
        if final in ctx.from_imports:
            mod, orig = ctx.from_imports[final]
            if orig == target_name:
                if _module_matches(mod, target_module, target_stem,
                                   stem_ambiguous):
                    return DIRECT_CALL, "HIGH"
                if mod.rsplit(".", 1)[-1] == target_stem:
                    return POSSIBLE_CALL, "LOW"  # ambiguous shared stem
            return None, "LOW"   # resolved to a DIFFERENT module/symbol
        if _stem_star(ctx, target_stem):
            return POSSIBLE_CALL, "LOW"
        return POSSIBLE_CALL, "LOW"

    # Attribute call: a.b.name() - the receiver must resolve.
    if target_kind == "method":
        if len(receiver_chain) == 1 and receiver_chain[0] in ("self", "cls"):
            if _inside_class(node, symbol, file_symbols):
                return DIRECT_CALL, "HIGH"
        if len(receiver_chain) == 1:
            base = receiver_chain[0]
            if base in ctx.from_imports:
                mod, orig = ctx.from_imports[base]
                if orig == target_class and _module_matches(
                        mod, target_module, target_stem, stem_ambiguous):
                    return DIRECT_CALL, "HIGH"
            if in_target_file and base == target_class:
                return DIRECT_CALL, "HIGH"   # Class.method() in the same file
        return POSSIBLE_CALL, "LOW"          # instance.method(): type unknown

    module = _chain_to_module(receiver_chain, ctx)
    if module is not None and _module_matches(
            module, target_module, target_stem, stem_ambiguous):
        return ATTRIBUTE_CALL, "MEDIUM"
    if in_target_file and len(receiver_chain) == 1 \
            and receiver_chain[0] == target_name:
        return DIRECT_CALL, "HIGH"
    return POSSIBLE_CALL, "LOW"


def _stem_star(ctx: _ImportCtx, target_stem: str) -> bool:
    return any(m.rsplit(".", 1)[-1] == target_stem for m in ctx.star_modules)


def _inside_class(node: ast.AST, symbol: Symbol,
                  file_symbols: List[Symbol]) -> bool:
    """Is the call site lexically inside the target method's class?"""
    if symbol.parent is None:
        return False
    for s in file_symbols:
        if s.kind == "class" and s.name == symbol.parent:
            if s.start_line <= node.lineno <= s.end_line:
                return True
    return False


def _status_for(path: str, change_map: Optional[Dict[str, str]]) -> str:
    """LIVE at the analyzed revision, or changed by the analyzed change."""
    if change_map:
        status = change_map.get(path)
        if status == "D":
            return "DELETED"
        if status in ("M", "R", "A"):
            return "MODIFIED"
    return "LIVE"


def _add_ref(refs: List[CallerRef], path: str, file_symbols: List[Symbol],
             line: int, rel: str, conf: str,
             change_map: Optional[Dict[str, str]], target_name: str) -> None:
    """Aggregate a caller reference per (path, caller symbol, relationship)."""
    caller = _innermost_symbol_at(file_symbols, line)
    caller_sym = f"{path}:{caller.name}" if caller else f"{path}:<module>"
    caller_name = caller.name if caller else "<module>"
    status = _status_for(path, change_map)
    for i, r in enumerate(refs):
        if r.path == path and r.symbol == caller_sym \
                and r.relationship == rel:
            refs[i] = CallerRef(
                symbol=caller_sym, path=path, name=caller_name,
                line=r.line, call_sites=r.call_sites + 1,
                relationship=rel, status=status, confidence=conf,
                text=_caller_text(caller_name, target_name, rel, path, r.line))
            return
    refs.append(CallerRef(
        symbol=caller_sym, path=path, name=caller_name,
        line=line, relationship=rel, status=status, confidence=conf,
        text=_caller_text(caller_name, target_name, rel, path, line)))


def _caller_text(caller: str, target: str, rel: str, path: str,
                 line: int) -> str:
    return f"{caller} → {target}()  {rel} at {path}:{line}"


def _name_in_text(content: str, name: str) -> bool:
    return bool(re.search(rf"\b{re.escape(name)}\b", content))


# ---------------------------------------------------------------------------
# Evidence integration
# ---------------------------------------------------------------------------

def collect_caller_evidence(repo: Repository, target: Target,
                            revision: str = "HEAD",
                            memo: AnalysisMemo = None,
                            change_map: Optional[Dict[str, str]] = None,
                            ) -> Tuple[List, List[CallerRef], Optional[Symbol]]:
    """Caller evidence for the target, or ([], [], None) when no symbol
    resolves.

    Returns (evidence_items, caller_refs, target_symbol). Only
    DIRECT/ATTRIBUTE/IMPORT/POSSIBLE classifications produce evidence;
    TEXTUAL_MATCH and UNRESOLVED stay in the callers list for transparency
    with zero weight. `target_symbol` is None for non-Python files,
    unparseable files, or lines outside any definition.
    """
    from .models import EvidenceItem
    if memo is None:
        from .analyzer import AnalysisMemo  # lazy: avoids import cycle
        memo = AnalysisMemo()
    sym = enclosing_symbol(repo, revision, target, memo)
    if sym is None:
        return [], [], None
    refs = discover_callers(repo, revision, sym, memo, change_map=change_map)

    ev = []
    for r in refs:
        if r.relationship in (DIRECT_CALL, ATTRIBUTE_CALL):
            w = weight_for("live_caller")
            reasons = [f"{r.relationship} at {r.path}:{r.line}"]
            if _is_test_path(r.path):
                w = 0.10
                reasons.append("caller is a test file (weaker signal)")
            ev.append(EvidenceItem(
                kind="live_caller", commit=None,
                text=f"confirmed live caller: {r.symbol}",
                weight=w, reasons=reasons, is_counter=False))
        elif r.relationship == IMPORT_REFERENCE:
            ev.append(EvidenceItem(
                kind="import_reference", commit=None,
                text=f"symbol/module imported by {r.path}",
                weight=weight_for("import_reference"),
                reasons=["module or symbol import found"], is_counter=False))
        elif r.relationship == POSSIBLE_CALL:
            ev.append(EvidenceItem(
                kind="possible_caller", commit=None,
                text=f"possible caller: {r.symbol} (resolution ambiguous)",
                weight=weight_for("possible_caller"),
                reasons=["name matches but the reference could not be "
                         "resolved confidently"], is_counter=False))
    return ev, refs, sym
