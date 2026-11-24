# Byakugan
<img width="1920" height="1080" alt="neji_byakugan" src="https://github.com/user-attachments/assets/107da7e5-0a67-4899-b274-61a0c75c52d8" />

Byakugan(name heavily inspired by Neji from Naruto) is a Python command-line tool for understanding the shape of a codebase. The first layer inventories source files, languages, and frameworks across Python, Java, JavaScript/TypeScript, and Go projects. It works on mixed repositories and monorepos without running the target code.



## Run

Python 3.10 or newer is required. From the repository checkout:

```sh
python -m byakugan scan /path/to/project
python -m byakugan scan /path/to/project --format json
python -m byakugan scan /path/to/project --format json --out project-map.json
```

Optionally, install the package with `pip install -e .` and use `byakugan scan ...`.

The report is a static, best-effort inventory. JSON output has `schemaVersion: 1`, `project`, `summary`, `files`, and `warnings`. File paths are relative to the scanned directory. Framework names include evidence from project manifests. Dependency and generated directories are skipped, and the scanner does not follow symlinks.

## Next layers

The inventory is the foundation for deeper adapters. The next commits should add Django models and routes, followed by Node/React, Java/Spring, and Go structure. Later layers can connect routes to handlers, services, and models, then support diagrams and change-impact questions. Each adapter should extend the common report format with source locations and tests.

Run the test suite with `python -m unittest discover -s tests -v`.
