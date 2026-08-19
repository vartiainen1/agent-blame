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

from .git import git_output, try_git_output
from .graph import _is_test_path
from .models import CallerRef, Symbol, Target
from .ranking import weight_for
from .repository import Repository
from .target import TargetError

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


def load_py_sources(repo: Repository, revision: str,
                    paths: Optional[List[str]] = None) -> Dict[str, str]:
    """Python source at `revision`, optionally restricted to `paths`.

    Exactly two git calls (ls-tree + one cat-file batch). Restricting to
    a pathspec keeps movement analysis proportional to the CHANGE size
    instead of the repository size (a move's source/destination are both
    in the change by definition). Sources are kept for the run only.
    """
    files = _ls_tree_py_files(repo, revision)
    if not files:
        return {}
    if paths is not None:
        files = {p: s for p, s in files.items() if p in set(paths)}
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


def index_sources(repo: Repository, paths: List[str]) -> Dict[str, str]:
    """Index (staged) content for `paths`, via ls-files + one cat-file batch.

    Used by --diff --staged movement analysis: the "after" side of a
    staged diff is the index, not the working tree. Two git calls total.
    """
    if not paths:
        return {}
    raw = git_output(["ls-files", "--stage", "-z", "--", *paths],
                     cwd=repo.root)
    blob_of: Dict[str, str] = {}
    for entry in raw.split("\x00"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split(" ")
        if len(parts) == 3 and path.endswith(".py"):
            blob_of[path] = parts[2]
    if not blob_of:
        return {}
    contents = _cat_file_batch(repo, sorted(set(blob_of.values())))
    out: Dict[str, str] = {}
    for path, sha in blob_of.items():
        content = contents.get(sha)
        if content is not None:
            out[path] = content
    return out


def worktree_sources(paths: List[str], root: str) -> Dict[str, str]:
    """Read `paths` from the working tree on disk (never executed).

    Used by --diff movement analysis: the "after" side of an unstaged
    diff is the working tree, which is not a git revision. Reads are
    bounded by the changed-file list and decoded with errors='replace'
    (source is untrusted input).
    """
    import os
    out: Dict[str, str] = {}
    for p in paths:
        if not p.endswith(".py"):
            continue
        try:
            with open(os.path.join(root, p), "r",
                      encoding="utf-8", errors="replace") as f:
                out[p] = f.read()
        except (OSError, ValueError):
            continue
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


def resolve_symbol(source: str, path: str, name: str) -> Symbol:
    """Resolve a function/method/class name to its defining Symbol.

    Phase 6C `file:function` entry point. Deterministic resolution rules
    (never a guess, mirroring the caller classifier's conservatism):
      - a QUALIFIED name (contains ".", e.g. "Server.handle") matches the
        symbol whose qualified name is exactly that - the qualified name
        IS the identity, so it must match exactly one symbol;
      - an unqualified (leaf) name must match exactly ONE symbol in the
        file - more than one is an ambiguity error naming the candidates
        (the user disambiguates with a qualified name), zero is a
        not-found error listing the available symbols.

    Raises TargetError (a clean usage error) on ambiguity/absence, never
    a traceback.
    """
    symbols = extract_symbols(source, path)
    if not symbols:
        raise TargetError(
            f"no symbols found in {path!r} (empty, unparseable, or not "
            "Python source)"
        )
    if "." in name:
        exact = [s for s in symbols if s.name == name]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise TargetError(_ambiguous_symbol_msg(path, name, exact))
        shown = ", ".join(s.name for s in symbols[:15])
        more = f" (+{len(symbols) - 15} more)" if len(symbols) > 15 else ""
        raise TargetError(
            f"no symbol {name!r} in {path}; available symbols: {shown}{more}"
        )
    leaf = [s for s in symbols if s.name.rsplit(".", 1)[-1] == name]
    if len(leaf) == 1:
        return leaf[0]
    if len(leaf) > 1:
        raise TargetError(_ambiguous_symbol_msg(path, name, leaf))
    shown = ", ".join(s.name for s in symbols[:15])
    more = f" (+{len(symbols) - 15} more)" if len(symbols) > 15 else ""
    raise TargetError(
        f"no function {name!r} in {path}; available symbols: {shown}{more}"
    )


def _ambiguous_symbol_msg(path: str, name: str, matches: List[Symbol]) -> str:
    """Deterministic ambiguity message naming every candidate."""
    cands = " and ".join(
        f"{path}:{s.name}" for s in sorted(matches, key=lambda s: s.name)
    )
    return (
        f"function {name!r} is ambiguous in {path}: matches {cands}; "
        "use the qualified name (e.g. <file>:<qualified.name>) to "
        "disambiguate"
    )


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

    # A call only references OUR symbol if its callee name IS the target's
    # name, or is a bare from-import ALIAS that deterministically resolves
    # to the target (`from auth import authenticate as auth_fn; auth_fn()`).
    # The discover-loop pre-filter admits any `final in ctx.from_imports`,
    # so WITHOUT this guard every bare call whose name happens to be an
    # import (cast(...), parse_url(...), ...) inside the target's class is
    # credited as a DIRECT_CALL of the target - the requests prepare_url
    # false-caller bug (Phase 4). Any other differently-named call is a
    # different symbol and is never a caller of ours.
    alias_resolved = (
        not receiver_chain
        and final != target_name
        and final in ctx.from_imports
        and ctx.from_imports[final][1] == target_name
        and _module_matches(ctx.from_imports[final][0], target_module,
                            target_stem, stem_ambiguous)
    )
    if final != target_name and not alias_resolved:
        return None, "LOW"

    if not receiver_chain:
        # bare call: authenticate() / check() / auth_fn() (resolved alias)
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
# Symbol-level movement matching (Phase 2D)
# ---------------------------------------------------------------------------

# Continuity thresholds (documented HEURISTICS, never probabilities):
# >= _STRONG_SIMILARITY with a clear margin and source removal = a
# confirmed move; >= _WEAK_SIMILARITY = possible move; below = no claim.
_STRONG_SIMILARITY = 0.85
_WEAK_SIMILARITY = 0.60
_MARGIN = 0.15          # best candidate must beat the runner-up by this


def _symbol_body(content: str, sym: Symbol) -> List[str]:
    """The symbol's source body, normalized for continuity comparison.

    Normalization: per-line leading/trailing whitespace stripped, blank
    lines dropped. Pure data comparison - never executed.
    """
    lines = content.splitlines()
    body = []
    for i in range(sym.start_line - 1, min(sym.end_line, len(lines))):
        t = lines[i].strip()
        if t:
            body.append(t)
    return body


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


def _continuity(a: List[str], b: List[str]) -> float:
    """Structural similarity of two symbol bodies (0.0 - 1.0), heuristic.

    WORD-level tokens (identifiers and numbers), not whole lines: a
    one-value change in a small function must not zero out the signal
    (a moved function with one modified line is POSSIBLE movement, not
    nothing). A wholesale rewrite shares almost no tokens and scores low.
    """
    from difflib import SequenceMatcher
    ta = [t for line in a for t in _TOKEN_RE.findall(line)]
    tb = [t for line in b for t in _TOKEN_RE.findall(line)]
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def _source_removed(before: Dict[str, str], before_sym: Symbol,
                    after_syms: List[Symbol],
                    after: Dict[str, str]) -> bool:
    """Is the BEFORE symbol's IMPLEMENTATION gone from the AFTER tree?

    The copy-vs-move distinction (spec 2D/13): the source counts as
    removed when no same-name symbol at its path still resembles it. A
    stub or full rewrite (the name survives but the body diverged beyond
    recognition) IS a removal - the real implementation moved away.
    """
    matches = [s for s in after_syms
               if s.path == before_sym.path and s.kind == before_sym.kind
               and _leaf(s.name) == _leaf(before_sym.name)]
    if not matches:
        return True
    before_body = _symbol_body(before.get(before_sym.path, ""), before_sym)
    for m in matches:
        if _continuity(before_body,
                       _symbol_body(after.get(m.path, ""), m)) \
                >= _WEAK_SIMILARITY:
            return False  # the source implementation still exists
    return True          # only a diverged/stubbed remnant remains


def _leaf(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def match_moved_symbols(repo: Repository, memo, before: Dict[str, str],
                        after: Dict[str, str],
                        rename_map: Optional[Dict[str, str]] = None,
                        ) -> List[dict]:
    """Symbols that appear to have MOVED between the before/after trees.

    Pure function over two content maps (revision blobs, index, or
    worktree reads - the caller decides the boundary). For each AFTER
    symbol that is new to its file, find BEFORE symbols of the same
    (kind, leaf name) at a DIFFERENT path and score structural
    continuity. A confirmed move requires: strong similarity, a clear
    margin over any competing candidate, AND removal from the source
    (otherwise it is a COPY, not a move). Ambiguity degrades to
    POSSIBLE_MOVEMENT - never a confident claim from a name match alone.

    Returns Movement-style dicts (type/source/dest/confidence/signals);
    origin tracing is the caller's job (blame the source range).
    """
    before_syms: List[Symbol] = []
    for path, content in before.items():
        before_syms.extend(extract_symbols(content, path))
    after_syms: List[Symbol] = []
    for path, content in after.items():
        after_syms.extend(extract_symbols(content, path))
    if not before_syms or not after_syms:
        return []

    # Index BEFORE symbols by (kind, leaf name).
    by_key: Dict[Tuple[str, str], List[Symbol]] = {}
    for s in before_syms:
        by_key.setdefault((s.kind, _leaf(s.name)), []).append(s)

    # AFTER identity: (path, qualified name) present before?
    before_ids = {(s.path, s.name) for s in before_syms}
    after_by_path: Dict[str, List[Symbol]] = {}
    for s in after_syms:
        after_by_path.setdefault(s.path, []).append(s)

    moves: List[dict] = []
    for dest in after_syms:
        if (dest.path, dest.name) in before_ids:
            continue  # already existed at this path: not a move
        key = (dest.kind, _leaf(dest.name))
        candidates = by_key.get(key, [])
        if not candidates:
            continue
        # Score EVERY different-path candidate (a move needs removal from
        # the source; a strong match WITH the source still present is a
        # COPY, never a move - spec 2D/13). "Removed" means the
        # implementation is gone: name absent, or only a diverged
        # stub/rewrite remains.
        scored = []
        for cand in candidates:
            if cand.path == dest.path:
                continue
            source_gone = _source_removed(before, cand, after_syms, after)
            score = _continuity(
                _symbol_body(before.get(cand.path, ""), cand),
                _symbol_body(after.get(dest.path, ""), dest))
            scored.append((score, cand, source_gone))
        if not scored:
            continue
        scored.sort(key=lambda t: -t[0])
        best_score, best, best_gone = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best_score < _WEAK_SIMILARITY:
            continue

        type_ = "POSSIBLE_MOVEMENT"
        confidence = "MEDIUM"
        signals = [f"symbol identity ({dest.kind} {_leaf(dest.name)})",
                   f"structural similarity {best_score:.2f}"]
        if not best_gone:
            # Strong similarity but the source still EXISTS: a copy, and
            # spec 2D/13 says never claim "moved" for a copy.
            if best_score >= _STRONG_SIMILARITY:
                moves.append({
                    "type": "COPY",
                    "source_path": best.path,
                    "source_symbol": best.name,
                    "dest_path": dest.path,
                    "dest_symbol": dest.name,
                    "moved_by": None,
                    "origin": None,
                    "origin_path": None,
                    "confidence": "HIGH",
                    "signals": [*signals,
                                 "source still exists - copy, not move"],
                    "_dest_start": dest.start_line,
                    "_dest_end": dest.end_line,
                    "_source_start": best.start_line,
                    "_source_end": best.end_line,
                })
            continue

        if best_score >= _STRONG_SIMILARITY \
                and best_score - runner_up >= _MARGIN:
            type_ = "CODE_MOVEMENT"
            confidence = "HIGH"
        elif best_score - runner_up < _MARGIN:
            type_ = "POSSIBLE_MOVEMENT"
            confidence = "AMBIGUOUS"  # competing possible origins
        signals.append("removed from source file")
        if rename_map and rename_map.get(dest.path) == best.path:
            signals.append("git rename metadata")
        moves.append({
            "type": type_,
            "source_path": best.path,
            "source_symbol": best.name,
            "dest_path": dest.path,
            "dest_symbol": dest.name,
            "moved_by": None,
            "origin": None,
            "origin_path": None,
            "confidence": confidence,
            "signals": signals,
            "_dest_start": dest.start_line,
            "_dest_end": dest.end_line,
            "_source_start": best.start_line,
            "_source_end": best.end_line,
        })
    return moves


def find_origin(repo: Repository, memo, blame_commit: str,
                revision: str, target: Target) -> Optional[dict]:
    """Does `blame_commit` merely MOVE code that existed earlier elsewhere?

    Standalone-mode correction for the case where git's rename detection
    failed (partial move): blame credits commit O with introducing the
    line at its CURRENT path, but the symbol existed at another path in
    O's parent. Loads the source index at O^ (memoized, one ls-tree +
    one cat-file batch) and matches symbols by (kind, leaf) + structural
    continuity, requiring removal from the source (a move, not a copy).
    Returns a Movement-style dict on a confirmed match, else None.

    Only the strongest signal is trusted: a genuine introduction has no
    matching symbol anywhere in O^'s tree, so this is a no-op there.
    """
    # The parent's metadata is almost always already cached (the blamed
    # commit is in the target file's commit list). Only fall back to a
    # fresh fetch for commits outside that list.
    ci = memo.commit_map.get(blame_commit)
    if ci is None:
        from .history import commit_info
        ci = commit_info(repo, blame_commit)
    if ci is None or not ci.parents:
        return None
    parent = ci.parents[0]
    if parent == revision:
        return None
    sym = enclosing_symbol(repo, revision, target, memo)
    if sym is None:
        return None
    leaf = _leaf(sym.name)

    # Cheap pre-filter (ONE git grep call, no blob fetch): only load the
    # parent's source index when some file at the parent could DEFINE this
    # name. A genuine introduction has no such file -> zero extra index
    # work. POSIX ERE has no \b; require a non-identifier char or EOL
    # after the name so `def authenticate_other` cannot match.
    pat = rf"(def|class)[[:space:]]+{re.escape(leaf)}([^[:alnum:]_]|$)"
    hits = try_git_output(["grep", "-l", "-z", "-E", pat, parent,
                           "--", "*.py"], cwd=repo.root)
    if not hits:
        return None
    # `git grep -l <rev>` prefixes every path with "<sha>:" - strip it
    # before the path lookup (paths themselves are NUL-delimited).
    _SHA_PREFIX = re.compile(r"^[0-9a-f]{40}:")
    hit_paths = []
    for p in hits.split("\x00"):
        p = _SHA_PREFIX.sub("", p)
        if p and p != target.file:
            hit_paths.append(p)
    if not hit_paths:
        return None
    sources_before = memo.py_sources_limited(repo, parent, hit_paths)
    if not sources_before:
        return None
    sources_after = memo.py_sources(repo, revision)

    key = (sym.kind, leaf)
    candidates = []
    for path, content in sources_before.items():
        for s in extract_symbols(content, path):
            if (s.kind, _leaf(s.name)) != key:
                continue
            # Source implementation must be gone from the blamed commit's
            # tree (name absent, or only a diverged stub remains).
            after_syms = [x for p, c in sources_after.items()
                          for x in extract_symbols(c, p)]
            if not _source_removed(sources_before, s, after_syms,
                                   sources_after):
                continue
            score = _continuity(
                _symbol_body(content, s),
                _symbol_body(sources_after.get(target.file, ""), sym))
            candidates.append((score, path, s))
    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    best_score, best_path, best_sym = candidates[0]
    runner_up = candidates[1][0] if len(candidates) > 1 else 0.0
    if best_score < _STRONG_SIMILARITY \
            or best_score - runner_up < _MARGIN:
        return None  # weak or ambiguous - do not claim a move
    return {
        "type": "CODE_MOVEMENT",
        "source_path": best_path,
        "source_symbol": best_sym.name,
        "dest_path": target.file,
        "dest_symbol": sym.name,
        "moved_by": blame_commit,
        "origin": None,       # caller blames the source range to fill this
        "origin_path": best_path,
        "confidence": "HIGH",
        "signals": [f"symbol identity ({sym.kind} {_leaf(sym.name)})",
                     f"structural similarity {best_score:.2f}",
                     "removed from source file",
                     "blame credits the move commit, not the introduction"],
        # Internal fields for the caller's origin tracing (stripped before
        # rendering): the source symbol's range and the mover's parent.
        "_parent": parent,
        "_source_start": best_sym.start_line,
        "_source_end": best_sym.end_line,
    }


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
