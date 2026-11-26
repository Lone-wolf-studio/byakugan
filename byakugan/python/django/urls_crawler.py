"""Extract Django URL patterns from a Python syntax tree."""

from __future__ import annotations

import ast


_URL_MODULES = {"django.urls", "django.conf.urls"}
_URL_FUNCTIONS = {"path", "re_path", "url"}


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _url_aliases(tree: ast.AST) -> tuple[dict[str, str], dict[str, str], set[str]]:
    url_calls: dict[str, str] = {}
    include_calls: dict[str, str] = {}
    url_modules: set[str] = set()
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in _URL_MODULES:
                    url_modules.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom) and statement.module in _URL_MODULES:
            for alias in statement.names:
                local_name = alias.asname or alias.name
                if alias.name in _URL_FUNCTIONS:
                    url_calls[local_name] = alias.name
                elif alias.name == "include":
                    include_calls[local_name] = alias.name
    return url_calls, include_calls, url_modules


def _pattern_values(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _pattern_values(node.left) + _pattern_values(node.right)
    return [node]


def extract_routes(tree: ast.AST) -> list[dict]:
    """Return literal URL patterns from recognizable ``urlpatterns`` values."""
    url_calls, include_calls, url_modules = _url_aliases(tree)

    def is_url_call(node: ast.expr) -> bool:
        name = _qualified_name(node)
        if name in url_calls:
            return True
        prefix, separator, function = (name or "").rpartition(".")
        return bool(separator and prefix in url_modules and function in _URL_FUNCTIONS)

    def is_include_call(node: ast.expr) -> bool:
        name = _qualified_name(node)
        if name in include_calls:
            return True
        prefix, separator, function = (name or "").rpartition(".")
        return bool(separator and prefix in url_modules and function == "include")

    pattern_nodes: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "urlpatterns" for target in node.targets):
            pattern_nodes.extend(_pattern_values(node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "urlpatterns" and node.value:
            pattern_nodes.extend(_pattern_values(node.value))
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "urlpatterns" and isinstance(node.op, ast.Add):
            pattern_nodes.extend(_pattern_values(node.value))

    routes = []
    seen = set()
    for pattern in pattern_nodes:
        if not isinstance(pattern, ast.Call) or not is_url_call(pattern.func) or len(pattern.args) < 2:
            continue
        route_path = pattern.args[0]
        handler = pattern.args[1]
        if not isinstance(route_path, ast.Constant) or not isinstance(route_path.value, str):
            # A dynamic route cannot be mapped reliably without executing code.
            continue
        is_include = isinstance(handler, ast.Call) and is_include_call(handler.func)
        route = {
            "path": route_path.value,
            "method": "ANY",
            "handler": ast.unparse(handler),
            "line": pattern.lineno,
            "kind": "include" if is_include else "route",
        }
        key = (route["line"], route["path"], route["handler"])
        if key not in seen:
            routes.append(route)
            seen.add(key)
    return sorted(routes, key=lambda item: (item["line"], item["path"]))
