# trade_ai/tools/architecture_validator.py
import ast
import os
from pathlib import Path

FORBIDDEN_IN_DOMAIN = ["pandas", "requests", "sql", "csv", "parquet", "telegram"]
DOMAIN_DIR = Path("trade_ai/domain")

def _collect_imports(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        node = ast.parse(f.read(), filename=str(file_path))
    imports = []
    for n in ast.walk(node):
        if isinstance(n, ast.Import):
            for alias in n.names:
                imports.append(alias.name)
        elif isinstance(n, ast.ImportFrom):
            module = n.module or ""
            imports.append(module)
    return imports

def validate_domain():
    errors = []
    for py in DOMAIN_DIR.rglob("*.py"):
        imps = _collect_imports(py)
        for forb in FORBIDDEN_IN_DOMAIN:
            for imp in imps:
                if imp and forb in imp:
                    errors.append(f"{py} imports forbidden module '{imp}' (contains '{forb}')")
    return errors

if __name__ == "__main__":
    errs = validate_domain()
    if errs:
        print("Architecture validation failed:")
        for e in errs:
            print("-", e)
        raise SystemExit(1)
    print("Architecture validation passed")
