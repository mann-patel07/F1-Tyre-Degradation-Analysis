import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"download_data.py", "run_telemetry.py", "download_seasons.py", "run_telemetry_season.py"}


def _imports_fastf1(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "fastf1" for a in node.names):
            yield node
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "fastf1":
            yield node


def test_only_allowed_files_import_fastf1():
    for p in ROOT.glob("*.py"):
        if p.name in ALLOWED:
            continue
        assert not list(_imports_fastf1(ast.parse(p.read_text()))), p.name


def test_telemetry_season_has_no_module_level_fastf1_import():
    tree = ast.parse((ROOT / "run_telemetry_season.py").read_text())
    for node in tree.body:
        assert not list(_imports_fastf1(ast.Module(body=[node], type_ignores=[]))) or not isinstance(node, (ast.Import, ast.ImportFrom))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [n for n in top if list(_imports_fastf1(ast.Module(body=[n], type_ignores=[])))]
