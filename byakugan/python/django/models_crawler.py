"""Extract Django model fields and relationships from a Python syntax tree."""

from __future__ import annotations

import ast


_RELATION_FIELDS = {"ForeignKey", "OneToOneField", "ManyToManyField"}


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


def _model_aliases(tree: ast.AST) -> tuple[set[str], set[str], dict[str, str]]:
    model_modules: set[str] = set()
    direct_model_names: set[str] = set()
    direct_fields: dict[str, str] = {}
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == "django.db.models":
                    model_modules.add(alias.asname or alias.name)
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
    return model_modules, direct_model_names, direct_fields


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


def extract_models(tree: ast.AST) -> list[dict]:
    """Return model facts for declarations with Django model imports."""
    model_modules, direct_model_names, direct_fields = _model_aliases(tree)
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
