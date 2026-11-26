"""Link static Django URL handlers to their Python definitions.

This module reads syntax trees from the scan's source bytes. It never imports
or executes the inspected project, and leaves uncertain handlers unresolved.
"""

from __future__ import annotations

import ast
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import PurePosixPath


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _module_file(
    importer: str,
    module: str,
    level: int,
    known: set[str],
) -> str | None:
    """Resolve an imported Python module to one unique scanned source file."""
    parts = [part for part in module.split(".") if part]
    if level:
        package_parts = list(PurePosixPath(importer).parent.parts)
        ascents = level - 1
        if ascents > len(package_parts):
            return None
        parts = package_parts[: len(package_parts) - ascents] + parts
    if not parts:
        return None

    stem = "/".join(parts)
    candidates = (f"{stem}.py", f"{stem}/__init__.py")
    exact = [candidate for candidate in candidates if candidate in known]
    if len(exact) == 1:
        return exact[0]
    if exact or level:
        return None

    # A monorepo may put a Python package under a single src/ or service root.
    matches = {
        path for path in known
        if any(path.endswith(f"/{candidate}") for candidate in candidates)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _bindings(
    tree: ast.Module,
    importer: str,
    known: set[str],
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Map local import names to module files and imported declarations."""
    modules: dict[str, str] = {}
    objects: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _module_file(importer, alias.name, 0, known)
                if target:
                    modules[alias.asname or alias.name] = target
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                prefix = node.module or ""
                imported_module = f"{prefix}.{alias.name}" if prefix else alias.name
                module_target = _module_file(importer, imported_module, node.level, known)
                if module_target:
                    modules[local] = module_target
                    continue
                if not prefix:
                    continue
                parent_target = _module_file(importer, prefix, node.level, known)
                if parent_target:
                    objects[local] = (parent_target, alias.name)
    return modules, objects


def _handler_target(handler: str) -> tuple[str, bool] | None:
    """Return the referenced name and whether it is a class-based view."""
    try:
        expression = ast.parse(handler, mode="eval").body
    except SyntaxError:
        return None
    if (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "as_view"
    ):
        name = _dotted_name(expression.func.value)
        return (name, True) if name else None
    name = _dotted_name(expression)
    return (name, False) if name else None


def _declaration(
    path: str,
    name: str,
    class_only: bool,
    sources: Mapping[str, bytes],
    trees: OrderedDict[str, ast.Module | None],
) -> dict[str, object] | None:
    if path in trees:
        tree = trees.pop(path)
        trees[path] = tree
    else:
        try:
            tree = ast.parse(sources[path], filename=path)
        except (KeyError, OSError, SyntaxError, ValueError):
            tree = None
        trees[path] = tree
        if len(trees) > 128:
            trees.popitem(last=False)
    if tree is None:
        return None
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
        and (not class_only or isinstance(node, ast.ClassDef))
    ]
    if len(matches) != 1:
        return None
    node = matches[0]
    return {
        "path": path,
        "name": name,
        "line": node.lineno,
        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
    }


def link_django_views(files: list[dict[str, object]], sources: Mapping[str, bytes]) -> int:
    """Attach source locations to uniquely resolved Django route handlers."""
    known = set(sources)
    trees: OrderedDict[str, ast.Module | None] = OrderedDict()
    linked = 0
    for file in files:
        importer = file.get("path")
        routes = file.get("routes")
        if not isinstance(importer, str) or not isinstance(routes, list) or importer not in known:
            continue
        try:
            url_tree = ast.parse(sources[importer], filename=importer)
        except (KeyError, OSError, SyntaxError, ValueError):
            continue
        modules, objects = _bindings(url_tree, importer, known)
        for route in routes:
            if not isinstance(route, dict) or route.get("kind") != "route":
                continue
            handler = route.get("handler")
            if not isinstance(handler, str):
                continue
            reference = _handler_target(handler)
            if reference is None:
                continue
            dotted, class_only = reference
            target: tuple[str, str] | None = None
            if dotted in objects:
                target = objects[dotted]
            else:
                prefix, separator, name = dotted.rpartition(".")
                if separator and prefix in modules:
                    target = (modules[prefix], name)
            if target is None:
                continue
            view = _declaration(*target, class_only, sources, trees)
            if view is not None:
                route["view"] = view
                linked += 1
    return linked
