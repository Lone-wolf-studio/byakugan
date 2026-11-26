"""Static Django model and URL pattern discovery.

The target source is parsed with Python's AST. It is never imported or run.
Only declarations with recognizable Django imports are reported.
"""

from __future__ import annotations

import ast

from .models_crawler import extract_models
from .urls_crawler import extract_routes


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

    return {
        "models": extract_models(tree),
        "routes": extract_routes(tree),
        "warnings": [],
    }
