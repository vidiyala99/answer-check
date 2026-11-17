"""Build a signature index from SDK source with `ast` only. SDK code is never imported or executed."""
from __future__ import annotations

import ast
from pathlib import Path

CLIENT_CLASSES = ('WorkOSClient', 'AsyncWorkOSClient')


def _default_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse handles all expressions in 3.9+
        return '...'


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    a = fn.args
    positional = [x.arg for x in a.posonlyargs + a.args]
    if positional and positional[0] in ('self', 'cls'):
        positional = positional[1:]
    pos_nodes = (a.posonlyargs + a.args)[-len(positional):] if positional else []
    # Defaults align to the tail of the positional parameters.
    pos_defaults = {}
    for node, default in zip(pos_nodes[len(pos_nodes) - len(a.defaults):], a.defaults):
        pos_defaults[node.arg] = _default_text(default)
    kw_defaults = {k.arg: _default_text(d) for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None}
    keyword_only = [k.arg for k in a.kwonlyargs]
    required = [p for p in positional if p not in pos_defaults] + [k for k in keyword_only if k not in kw_defaults]
    return {
        'positional': positional,
        'keyword_only': keyword_only,
        'required': required,
        'defaults': {**pos_defaults, **kw_defaults},
        'varargs': a.vararg is not None,
        'varkw': a.kwarg is not None,
        'line': fn.lineno,
    }


def _base_names(cls: ast.ClassDef) -> list[str]:
    out = []
    for b in cls.bases:
        if isinstance(b, ast.Name):
            out.append(b.id)
        elif isinstance(b, ast.Attribute):
            out.append(b.attr)
    return out


def _accessors(cls: ast.ClassDef) -> dict[str, str]:
    """Client accessors are properties whose return annotation names the resource class."""
    out = {}
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name.startswith('_'):
            continue
        is_prop = any(
            (isinstance(d, ast.Attribute) and d.attr in ('cached_property', 'property'))
            or (isinstance(d, ast.Name) and d.id in ('cached_property', 'property'))
            for d in fn.decorator_list
        )
        ann = fn.returns
        if is_prop and isinstance(ann, ast.Name):
            out[fn.name] = ann.id
        elif is_prop and isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            out[fn.name] = ann.value
    return out


def build_index(sdk_src: Path | str, version: str | None = None) -> dict:
    sdk_src = Path(sdk_src)
    classes: dict[str, dict] = {}
    clients: dict[str, dict] = {}
    skipped: list[str] = []
    for f in sorted(sdk_src.rglob('*.py')):
        rel = f.relative_to(sdk_src).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            skipped.append(rel)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name in CLIENT_CLASSES:
                clients[node.name] = _accessors(node)
            methods = {
                fn.name: {**_signature(fn), 'file': rel}
                for fn in node.body
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not fn.name.startswith('_')
            }
            entry = {'file': rel, 'bases': _base_names(node), 'methods': methods}
            # First definition wins; record collisions so they are visible, never silently merged.
            if node.name in classes:
                classes[node.name].setdefault('duplicates', []).append(rel)
            else:
                classes[node.name] = entry
    return {'sdk_version': version, 'clients': clients, 'classes': classes, 'skipped_files': skipped}


def resolve_method(index: dict, cls_name: str, method: str, _seen: frozenset = frozenset()) -> dict | None:
    """Find a method on a class or its bases (depth-first, as Python's MRO does for single inheritance)."""
    cls = index['classes'].get(cls_name)
    if cls is None or cls_name in _seen:
        return None
    if method in cls['methods']:
        return cls['methods'][method]
    for base in cls['bases']:
        found = resolve_method(index, base, method, _seen | {cls_name})
        if found:
            return found
    return None


def all_methods(index: dict, cls_name: str, _seen: frozenset = frozenset()) -> set[str]:
    cls = index['classes'].get(cls_name)
    if cls is None or cls_name in _seen:
        return set()
    names = set(cls['methods'])
    for base in cls['bases']:
        names |= all_methods(index, base, _seen | {cls_name})
    return names
