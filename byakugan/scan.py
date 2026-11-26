"""Static, dependency-free discovery for the first Byakugan CLI layer."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from .python.django import analyze_django
from .python.django.views import link_django_views


_LANGUAGES = {
    ".py": "Python",
    ".java": "Java",
    ".go": "Go",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
}
_SKIP_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "vendor", "dist", "build", "target", "coverage", "__pycache__",
    ".next", ".nuxt", ".turbo", ".cache", ".idea", ".gradle", "out",
}
_MAX_FILE_BYTES = 512 * 1024
_MAX_SOURCE_FILES = 10_000


def _relative(root: Path, file: Path) -> str:
    return file.relative_to(root).as_posix()


def _discover(root: Path, warnings: list[str]) -> list[Path]:
    """Find regular files without following links into another directory."""
    found: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
        except OSError as error:
            warnings.append(f"Cannot list {_relative(root, directory) or '.'}: {type(error).__name__}")
            return

        for entry in entries:
            child = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRECTORIES:
                        visit(child)
                elif entry.is_file(follow_symlinks=False):
                    found.append(child)
            except OSError as error:
                warnings.append(f"Cannot inspect {_relative(root, child)}: {type(error).__name__}")

    visit(root)
    return sorted(found, key=lambda file: (_relative(root, file).casefold(), _relative(root, file)))


def _read_small(root: Path, file: Path, warnings: list[str]) -> bytes | None:
    relative = _relative(root, file)
    try:
        with file.open("rb") as stream:
            content = stream.read(_MAX_FILE_BYTES + 1)
    except OSError as error:
        warnings.append(f"Cannot read {relative}: {type(error).__name__}")
        return None
    if len(content) > _MAX_FILE_BYTES:
        warnings.append(f"Skipped {relative}: larger than {_MAX_FILE_BYTES} bytes")
        return None
    if b"\0" in content:
        warnings.append(f"Skipped {relative}: binary content")
        return None
    return content


class _LazyPythonSources(Mapping[str, bytes]):
    """Expose scanned Python files without keeping their contents in memory."""

    def __init__(self, root: Path, paths: dict[str, Path], warnings: list[str]) -> None:
        self._root = root
        self._paths = paths
        self._warnings = warnings

    def __getitem__(self, relative: str) -> bytes:
        file = self._paths[relative]
        source = _read_small(self._root, file, self._warnings)
        if source is None:
            raise KeyError(relative)
        return source

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)


def _frameworks(
    root: Path,
    paths: list[Path],
    warnings: list[str],
    files: list[dict[str, object]],
) -> list[dict[str, object]]:
    found: dict[str, set[str]] = {}

    def add(name: str, evidence: str) -> None:
        found.setdefault(name, set()).add(evidence)

    for file in paths:
        name = file.name
        if name not in {
            "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
            "pom.xml", "build.gradle", "build.gradle.kts", "go.mod",
        }:
            continue
        relative = _relative(root, file)
        raw = _read_small(root, file, warnings)
        if raw is None:
            continue
        content = raw.decode("utf-8", errors="replace")

        if name == "package.json":
            try:
                manifest = json.loads(content)
                if not isinstance(manifest, dict):
                    raise ValueError("Expected a JSON object")
            except (json.JSONDecodeError, ValueError):
                warnings.append(f"Cannot parse {relative} as package.json")
                continue
            dependencies: dict[str, object] = {}
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                value = manifest.get(section)
                if isinstance(value, dict):
                    dependencies.update(value)
            for package, framework in (
                ("react", "React"), ("next", "Next.js"),
                ("express", "Express"), ("@nestjs/core", "NestJS"),
                ("vue", "Vue"), ("@angular/core", "Angular"),
            ):
                if package in dependencies:
                    add(framework, f"{relative}: {package}")
        elif name in {"requirements.txt", "pyproject.toml", "Pipfile"}:
            # These formats differ. Dependency names are enough for a first inventory.
            for package, framework in (("django", "Django"), ("fastapi", "FastAPI"), ("flask", "Flask")):
                if re.search(rf"\b{package}\b", content, flags=re.IGNORECASE):
                    add(framework, relative)
        elif name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
            if "spring-boot" in content.lower():
                add("Spring Boot", relative)
        elif name == "go.mod" and "github.com/gin-gonic/gin" in content:
            add("Gin", relative)

    basenames = {file.name for file in paths}
    if "manage.py" in basenames and "settings.py" in basenames:
        add("Django", "manage.py + settings.py")
    for file in files:
        if file.get("models"):
            add("Django", f"{file['path']}: model declarations")
        if file.get("routes"):
            add("Django", f"{file['path']}: URL patterns")
    return [
        {"name": name, "evidence": sorted(evidence)}
        for name, evidence in sorted(found.items())
    ]


def scan_project(directory: str | Path) -> dict[str, object]:
    """Return a deterministic map of recognized source files and frameworks.

    Project code is read as data. Nothing in the target project is imported,
    executed, installed, or built.
    """
    root = Path(directory).resolve()
    if not root.exists():
        raise ValueError(f"Directory does not exist: {directory}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    warnings: list[str] = []
    paths = _discover(root, warnings)
    sources = [file for file in paths if file.suffix.lower() in _LANGUAGES]
    if len(sources) > _MAX_SOURCE_FILES:
        warnings.append(
            f"Source file limit reached: scanning first {_MAX_SOURCE_FILES} of {len(sources)}"
        )

    files: list[dict[str, object]] = []
    python_paths: dict[str, Path] = {}
    counts: dict[str, int] = {}
    model_count = 0
    route_count = 0
    for file in sources[:_MAX_SOURCE_FILES]:
        source = _read_small(root, file, warnings)
        if source is None:
            continue
        language = _LANGUAGES[file.suffix.lower()]
        relative = _relative(root, file)
        entry: dict[str, object] = {"path": relative, "language": language}
        if language == "Python":
            python_paths[relative] = file
            findings = analyze_django(relative, source)
            warnings.extend(findings["warnings"])
            if findings["models"]:
                entry["models"] = findings["models"]
                model_count += len(findings["models"])
            if findings["routes"]:
                entry["routes"] = findings["routes"]
                route_count += len(findings["routes"])
        files.append(entry)
        counts[language] = counts.get(language, 0) + 1

    resolved_views = link_django_views(files, _LazyPythonSources(root, python_paths, warnings))
    return {
        "schemaVersion": 1,
        "project": {"name": root.name},
        "summary": {
            "sourceFiles": len(files),
            "languages": dict(sorted(counts.items())),
            "frameworks": _frameworks(root, paths, warnings, files),
            "models": model_count,
            "routes": route_count,
            "resolvedViews": resolved_views,
        },
        "files": files,
        "warnings": sorted(set(warnings)),
    }
