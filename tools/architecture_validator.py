# tools/architecture_validator.py

import ast
import os
from pathlib import Path
from typing import Dict, List, Set

# tools/architecture_validator.py lives at: <project_root>/tools/architecture_validator.py
# We want to validate imports within <project_root> (the bot_trade folder),
# not the parent directories (which could include unrelated files).
PROJECT_ROOT = Path(__file__).resolve().parents[1]

LAYER_MAP = {
    "domain": "domain",
    "feature_engineering": "feature",
    "application": "application",
    "infrastructure": "infra",
    "interfaces": "interfaces",
    "tools": "tools",
}

FORBIDDEN_IN_DOMAIN = {
    "pandas",
    "numpy",
    "torch",
    "sklearn",
    "requests",
    "sqlalchemy",
    "fastapi",
    "pyarrow",
}

RUNTIME_LAYERS = {"domain", "feature", "application", "infra", "interfaces"}


class ArchitectureViolation(Exception):
    pass


class ArchitectureValidator:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.violations: List[str] = []

    def run(self):
        for py_file in self._collect_python_files():
            self._validate_file(py_file)

        if self.violations:
            raise ArchitectureViolation(
                "\n".join(self.violations)
            )

        print("Architecture validation passed.")

    def _collect_python_files(self) -> List[Path]:
        return list(self.project_root.rglob("*.py"))

    def _detect_layer(self, file_path: Path) -> str:
        for part in file_path.parts:
            if part in LAYER_MAP:
                return LAYER_MAP[part]
        return "unknown"

    def _validate_file(self, file_path: Path):
        layer = self._detect_layer(file_path)

        if layer == "unknown":
            return

        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._check_import(node, layer, file_path)

    def _check_import(self, node, layer: str, file_path: Path):
        modules = []

        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules = [node.module]

        for module in modules:
            top = module.split(".")[0]

            # 1. tools cannot be imported by runtime
            if top == "tools" and layer in RUNTIME_LAYERS:
                self._add_violation(
                    file_path,
                    f"{layer} layer importing tools is forbidden"
                )

            # 2. domain restrictions
            if layer == "domain" and top in FORBIDDEN_IN_DOMAIN:
                self._add_violation(
                    file_path,
                    f"domain cannot import {top}"
                )

            # 3. clean architecture direction
            imported_layer = LAYER_MAP.get(top)

            if imported_layer:
                if not self._is_allowed(layer, imported_layer):
                    self._add_violation(
                        file_path,
                        f"{layer} cannot import {imported_layer}"
                    )

    def _is_allowed(self, from_layer: str, to_layer: str) -> bool:
        rules = {
            "domain": {"domain"},
            "feature": {"domain"},
            "application": {"domain", "feature"},
            "infra": {"domain"},
            "interfaces": {"application", "domain", "infra"},
            "tools": {"domain", "feature", "application", "infra", "interfaces", "tools"},
        }

        return to_layer in rules.get(from_layer, set())

    def _add_violation(self, file_path: Path, message: str):
        self.violations.append(f"{file_path}: {message}")


if __name__ == "__main__":
    validator = ArchitectureValidator(PROJECT_ROOT)
    validator.run()
