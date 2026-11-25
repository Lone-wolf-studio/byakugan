"""Command-line entry point for a static project inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .scan import scan_project


def render_text(report: dict) -> str:
    """Render a compact report; JSON contains the complete inventory."""
    summary = report["summary"]
    languages = ", ".join(
        f"{name} {count}" for name, count in summary["languages"].items()
    ) or "none"
    frameworks = "; ".join(
        f"{item['name']} ({', '.join(item['evidence'])})"
        for item in summary["frameworks"]
    ) or "none detected"
    lines = [
        f"Byakugan: {report['project']['name']}",
        "Static project inventory (best effort)",
        "",
        f"Source files: {summary['sourceFiles']}",
        f"Languages: {languages}",
        f"Frameworks: {frameworks}",
    ]
    models = [
        (file["path"], model)
        for file in report["files"]
        for model in file.get("models", [])
    ]
    routes = [
        (file["path"], route)
        for file in report["files"]
        for route in file.get("routes", [])
    ]
    lines.extend(["", f"Models ({len(models)}):"])
    for file_path, model in models[:30]:
        lines.append(f"  {model['name']}  {file_path}:{model['line']}")
        for field in model["fields"]:
            lines.append(f"    {field['name']}: {field['type']}")
        for relationship in model["relationships"]:
            lines.append(f"    {relationship['field']} → {relationship['target']}")
    if len(models) > 30:
        lines.append(f"  … {len(models) - 30} more in JSON output")
    lines.extend(["", f"Routes ({len(routes)}):"])
    for file_path, route in routes[:30]:
        lines.append(
            f"  {route['method']} {route['path']} → {route['handler']}  {file_path}:{route['line']}"
        )
    if len(routes) > 30:
        lines.append(f"  … {len(routes) - 30} more in JSON output")
    if report["warnings"]:
        lines.extend(["", f"Warnings ({len(report['warnings'])}):"])
        lines.extend(f"  {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="byakugan",
        description="Get a quick, static inventory of a project.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    scan = subcommands.add_parser("scan", help="inventory a project directory")
    scan.add_argument("directory", type=Path)
    scan.add_argument("--format", choices=("text", "json"), default="text")
    scan.add_argument("--out", type=Path, help="write the report to a file")
    args = parser.parse_args(argv)

    try:
        report = scan_project(args.directory)
        rendered = (
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            if args.format == "json"
            else render_text(report)
        )
        if args.out:
            args.out.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError) as error:
        parser.exit(2, f"byakugan: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
