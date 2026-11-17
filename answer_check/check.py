"""Check SDK calls in a drafted answer's Python code against a signature index. Deterministic, no LLM."""
from __future__ import annotations

import ast
import difflib
import re

from .sigindex import all_methods, resolve_method

FENCE = re.compile(r'```([^\n`]*)\n(.*?)```', re.S)
PY_LANGS = {'python', 'py', 'python3'}
DEFAULT_CLIENT_NAMES = {'client': 'WorkOSClient', 'workos': 'WorkOSClient', 'workos_client': 'WorkOSClient'}


def python_blocks(text: str) -> list[str]:
    out = []
    for m in FENCE.finditer(text):
        lang = m.group(1).strip().split()[0].lower() if m.group(1).strip() else ''
        if lang in PY_LANGS:
            out.append(m.group(2))
    return out


def render_signature(name: str, sig: dict) -> str:
    parts = []
    for p in sig['positional']:
        parts.append(f"{p}={sig['defaults'][p]}" if p in sig['defaults'] else p)
    if sig['varargs']:
        parts.append('*args')
    elif sig['keyword_only']:
        parts.append('*')
    for k in sig['keyword_only']:
        parts.append(f"{k}={sig['defaults'][k]}" if k in sig['defaults'] else k)
    if sig['varkw']:
        parts.append('**kwargs')
    return f"{name}({', '.join(parts)})"


def _suggest(word: str, options: list[str]) -> str | None:
    stripped = word.rstrip('_')
    if stripped != word and stripped in options:
        return stripped
    close = difflib.get_close_matches(word, options, n=1, cutoff=0.6)
    return close[0] if close else None


class _Scope:
    """Tracks which local names hold a WorkOS client or a resource accessor."""

    def __init__(self):
        self.clients = dict(DEFAULT_CLIENT_NAMES)  # name -> client class
        self.resources = {}  # name -> (accessor, resource class)


def _constructor_client(value: ast.expr) -> str | None:
    if isinstance(value, ast.Await):
        value = value.value
    if isinstance(value, ast.Call):
        f = value.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if name in ('WorkOSClient', 'AsyncWorkOSClient'):
            return name
    return None


def _resolve_resource(node: ast.expr, scope: _Scope, index: dict):
    """`client.users` -> ('users', 'Users'); alias name -> stored tuple; else None."""
    if isinstance(node, ast.Name) and node.id in scope.resources:
        return scope.resources[node.id]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in scope.clients:
        client_cls = scope.clients[node.value.id]
        accessors = index['clients'].get(client_cls, {})
        return (node.attr, accessors.get(node.attr))  # class None = unknown accessor
    return None


def _homes(method: str, index: dict, client_cls: str) -> list[str]:
    """Accessors on the client whose resource class has `method` (sorted; aliases of one class all listed)."""
    return sorted(acc for acc, cls in index['clients'].get(client_cls, {}).items()
                  if cls and resolve_method(index, cls, method) is not None)


def _check_call(call: ast.Call, accessor: str, cls_name: str | None, index: dict, client_cls: str) -> dict:
    method = call.func.attr
    rec = {'call': f'{accessor}.{method}', 'line': call.lineno, 'verdict': 'ok', 'problems': [],
           'signature': None, 'hint': ''}
    homes = _homes(method, index, client_cls) if (cls_name is None or
                                                  resolve_method(index, cls_name, method) is None) else []
    moved = f'; `{method}` is on `client.{homes[0]}.{method}`' + (
        f" (also {', '.join(f'`{h}`' for h in homes[1:])})" if len(homes) > 1 else '') + '.' if homes else ''
    if cls_name is None:
        # Only the method's real home is a safe suggestion; a fuzzy accessor guess for a method that exists
        # nowhere sent readers to an unrelated resource (organizations_it_contacts -> organization_domains).
        s = homes[0] if homes else None
        rec['verdict'] = 'unknown-method'
        rec['problems'].append({'kind': 'unknown-accessor', 'accessor': accessor, 'suggest': s})
        rec['hint'] = f'The client has no `{accessor}` resource' + (
            moved or f', and no resource on the client has `{method}` (SDK {index.get("sdk_version")}).')
        return rec
    sig = resolve_method(index, cls_name, method)
    if sig is None:
        s = _suggest(method, sorted(all_methods(index, cls_name)))
        rec['verdict'] = 'unknown-method'
        rec['problems'].append({'kind': 'unknown-method', 'method': method, 'suggest': s,
                                'found_on': homes or None})
        rec['hint'] = f'`{accessor}` has no method `{method}`' + (
            moved or (f'; did you mean `{s}`?' if s else '.'))
        return rec
    rec['signature'] = render_signature(method, sig)
    if any(k.arg is None for k in call.keywords) or any(isinstance(a, ast.Starred) for a in call.args):
        rec['verdict'] = 'not-checked'
        rec['hint'] = 'Arguments are unpacked (* or **); names cannot be checked statically.'
        return rec
    params = sig['positional'] + sig['keyword_only']
    problems = []
    n_pos = len(call.args)
    if n_pos > len(sig['positional']) and not sig['varargs']:
        problems.append({'kind': 'too-many-positional', 'given': n_pos, 'allowed': len(sig['positional'])})
    filled = set(sig['positional'][:n_pos])
    for kw in call.keywords:
        if kw.arg in params:
            filled.add(kw.arg)
        elif not sig['varkw']:
            problems.append({'kind': 'unknown-keyword', 'keyword': kw.arg, 'suggest': _suggest(kw.arg, params)})
    for req in sig['required']:
        if req not in filled and not any(p.get('suggest') == req for p in problems):
            problems.append({'kind': 'missing-required', 'param': req})
    if problems:
        rec['verdict'] = 'wrong-arg'
        rec['problems'] = problems
        fixes = []
        for p in problems:
            if p['kind'] == 'unknown-keyword':
                fixes.append(f"`{p['keyword']}` is not a parameter" + (f"; use `{p['suggest']}`" if p['suggest'] else ''))
            elif p['kind'] == 'missing-required':
                fixes.append(f"`{p['param']}` is required")
            else:
                fixes.append(f"takes at most {p['allowed']} positional argument(s), got {p['given']}")
        rec['hint'] = f"`{accessor}.{method}`: " + '; '.join(fixes) + f". Signature: `{rec['signature']}`."
    return rec


def check_block(code: str, index: dict) -> tuple[list[dict], str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return [], 'syntax-error'
    scope = _Scope()
    calls = []
    # Walk statements in source order so assignments are seen before later uses.
    for node in sorted(ast.walk(tree), key=lambda n: (getattr(n, 'lineno', 0), getattr(n, 'col_offset', 0))):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            client = _constructor_client(node.value)
            if client:
                scope.clients[name] = client
                continue
            res = _resolve_resource(node.value, scope, index)
            if res and res[1]:
                scope.resources[name] = res
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func.value
            res = _resolve_resource(target, scope, index)
            if res is None:
                continue
            client_cls = (scope.clients.get(target.value.id) if isinstance(target, ast.Attribute)
                          else 'WorkOSClient')
            calls.append(_check_call(node, res[0], res[1], index, client_cls or 'WorkOSClient'))
    return calls, 'parsed'


def check_answer(text: str, index: dict) -> dict:
    blocks, calls = [], []
    for i, code in enumerate(python_blocks(text)):
        found, status = check_block(code, index)
        blocks.append({'block': i, 'status': status, 'calls': len(found)})
        for c in found:
            calls.append({'block': i, **c})
    bad = [c for c in calls if c['verdict'] in ('wrong-arg', 'unknown-method')]
    return {'ok': not bad, 'sdk_version': index.get('sdk_version'), 'blocks': blocks, 'calls': calls,
            'repair_hints': [c['hint'] for c in bad]}
