"""Static Django model and URL pattern discovery.

The target source is parsed with Python's AST. It is never imported or run.
Only declarations with recognizable Django imports are reported.
"""

from __future__ import annotations

import ast


_RELATION_FIELDS = {"ForeignKey", "OneToOneField", "ManyToManyField"}
_URL_MODULES = {"django.urls", "django.conf.urls"}
_URL_FUNCTIONS = {"path", "re_path", "url"}


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _literal_or_expression(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def _import_aliases(tree: ast.AST) -> tuple[set[str], set[str], dict[str, str], dict[str, str], dict[str, str], set[str]]:
    """Return model module prefixes, direct fields, URL calls, include calls."""
    model_modules: set[str] = set()
    direct_model_names: set[str] = set()
    direct_fields: dict[str, str] = {}
    url_calls: dict[str, str] = {}
    include_calls: dict[str, str] = {}
    url_modules: set[str] = set()

    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == "django.db.models":
                    model_modules.add(alias.asname or alias.name)
                elif alias.name in _URL_MODULES:
                    url_modules.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom):
            if statement.module == "django.db":
                for alias in statement.names:
                    if alias.name == "models":
                        model_modules.add(alias.asname or "models")
            elif statement.module == "django.db.models":
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    if alias.name == "Model":
                        direct_model_names.add(local_name)
                    elif alias.name.endswith("Field") or alias.name == "ForeignKey":
                        direct_fields[local_name] = alias.name
            elif statement.module in _URL_MODULES:
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    if alias.name in _URL_FUNCTIONS:
                        url_calls[local_name] = alias.name
                    elif alias.name == "include":
                        include_calls[local_name] = alias.name

    return model_modules, direct_model_names, direct_fields, url_calls, include_calls, url_modules


def _django_field(call: ast.Call, model_modules: set[str], direct_fields: dict[str, str]) -> str | None:
    name = _qualified_name(call.func)
    if not name:
        return None
    if name in direct_fields:
        return direct_fields[name]
    prefix, separator, field_type = name.rpartition(".")
    if separator and prefix in model_modules and (field_type.endswith("Field") or field_type == "ForeignKey"):
        return field_type
    return None


def _models(tree: ast.AST, model_modules: set[str], direct_model_names: set[str], direct_fields: dict[str, str]) -> list[dict]:
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {_qualified_name(base) for base in node.bases}
        if not (bases & direct_model_names or any(f"{module}.Model" in bases for module in model_modules)):
            continue
        model = {"name": node.name, "line": node.lineno, "fields": [], "relationships": []}
        for statement in node.body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
                targets = [target.id for target in statement.targets if isinstance(target, ast.Name)]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and isinstance(statement.value, ast.Call):
                targets = [statement.target.id]
                value = statement.value
            else:
                continue
            field_type = _django_field(value, model_modules, direct_fields)
            if not field_type:
                continue
            for field_name in targets:
                model["fields"].append({"name": field_name, "type": field_type, "line": statement.lineno})
                if field_type in _RELATION_FIELDS:
                    target = next((keyword.value for keyword in value.keywords if keyword.arg == "to"), None)
                    if target is None and value.args:
                        target = value.args[0]
                    if target is not None:
                        model["relationships"].append({
                            "field": field_name,
                            "target": _literal_or_expression(target),
                            "kind": field_type,
                            "line": statement.lineno,
                        })
        result.append(model)
    return sorted(result, key=lambda item: (item["line"], item["name"]))


def _pattern_values(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _pattern_values(node.left) + _pattern_values(node.right)
    return [node]


def _routes(tree: ast.AST, url_calls: dict[str, str], include_calls: dict[str, str], url_modules: set[str]) -> list[dict]:
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


def analyze_django(relative_path: str, source: bytes) -> dict:
    """Extract recognized Django declarations with source line numbers."""
    empty = {"models": [], "routes": [], "warnings": []}
    try:
        tree = ast.parse(source, filename=relative_path)
    except (SyntaxError, ValueError) as error:
        line = getattr(error, "lineno", None)
        location = f"{relative_path}:{line}" if line else relative_path
        empty["warnings"].append(f"Cannot parse {location}: {getattr(error, 'msg', str(error))}")
        return empty

    model_modules, direct_model_names, direct_fields, url_calls, include_calls, url_modules = _import_aliases(tree)
    return {
        "models": _models(tree, model_modules, direct_model_names, direct_fields),
        "routes": _routes(tree, url_calls, include_calls, url_modules),
        "warnings": [],
    }
