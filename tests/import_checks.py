"""Offline import checks: no app imports, downloads, accounts or media fixtures."""
import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, assertion):
    if not assertion:
        raise AssertionError(name)
    results.append({"check": name, "status": "PASS"})


trees = {}
source_paths = sorted((ROOT / "app").glob("*.py")) + [ROOT / "Song" / "auto_cut_reels.py"]
for path in source_paths:
    text = path.read_text(encoding="utf-8-sig")
    trees[path.stem] = ast.parse(text, filename=str(path))
    compile(text, str(path), "exec")
    check("compile:" + path.name, True)

# Evaluate only the isolated BASE assignment; never execute application startup.
base_node = next(n for n in trees["app"].body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "BASE" for t in n.targets))
scope = {"Path": Path, "__file__": str(ROOT / "app" / "app.py")}
exec(compile(ast.Module(body=[base_node], type_ignores=[]), "BASE", "exec"), scope)
check("runtime-root-is-checkout", scope["BASE"] == ROOT)
for filename in ("Run_Hair_Tutorial_Tool.cmd", "Run_Hair_Tutorial_Tool_Silent.vbs"):
    text = (ROOT / filename).read_text(encoding="utf-8-sig")
    check("launcher-isolation:" + filename, "C:\\E\\HairTutorial" not in text
          and "C:\\Users\\" not in text)

# Execute only audited pure rule declarations/functions, with synthetic metadata.
keep = {"CATEGORY_RULES", "STYLE_RULES", "_pick_rule", "classify", "evaluate_video"}
nodes = [n for n in trees["media_pipeline"].body
         if (isinstance(n, ast.FunctionDef) and n.name in keep)
         or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in keep
                                             for t in n.targets))]
pure = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "pure-media-rules", "exec"), pure)
check("synthetic-classification", pure["classify"]("claw clip half-up tutorial")
      == ("hair-claw", "half-up"))
check("unknown-category-fallback", pure["classify"]("synthetic unknown")
      == ("beauty", "general"))
base = {"short_edge": 720, "duration_seconds": 8, "vertical_9_16": True,
        "average_sharpness": 50, "average_brightness": 100, "black_border_score": 0}
cases = [("minimum-boundary", {}, "ready"),
         ("maximum-boundary", {"duration_seconds": 45}, "ready"),
         ("low-resolution", {"short_edge": 719}, "low-resolution"),
         ("too-short", {"duration_seconds": 7.9}, "too-short"),
         ("needs-trim", {"duration_seconds": 45.1}, "needs-trim"),
         ("landscape-review", {"vertical_9_16": False}, "needs-review"),
         ("blur-review", {"average_sharpness": 34}, "needs-review"),
         ("dark-review", {"average_brightness": 34}, "needs-review"),
         ("border-review", {"black_border_score": 0.5}, "needs-review")]
for name, values, expected in cases:
    check(name, pure["evaluate_video"]({**base, **values})[0] == expected)
check("credential-config-absent", not (ROOT / "stockos_connector.json").exists()
      and not (ROOT / ".stockos_connector.key").exists())
helper = ROOT / "Song" / "auto_cut_reels.py"
check("song-helper-available", helper.is_file())
helper_imports = {n.module.split(".")[0] for n in ast.walk(trees["auto_cut_reels"])
                  if isinstance(n, ast.ImportFrom) and n.module}
helper_imports.update(alias.name.split(".")[0] for n in ast.walk(trees["auto_cut_reels"])
                      if isinstance(n, ast.Import) for alias in n.names)
import sys
check("song-helper-stdlib-only", helper_imports <= sys.stdlib_module_names)

# Hypothetical synthetic paths only: Git checks ignore rules without creating files.
ignore_cases = [(".stockos_connector.key", True), (".stockos_connector.key.tmp", True),
                ("nested/.stockos_connector.key.tmp", True), ("stockos_connector.json", True),
                (".env", True), ("app/browser_profile/Default/Cookies", True),
                ("app/vendor/package.py", True), ("Song/example.mp3", True),
                ("Song/Reels_Cuts/report.csv", True), ("Song/auto_cut_reels.py", False)]
for path, expected in ignore_cases:
    result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--", path],
                            capture_output=True, text=True, timeout=10)
    check("ignore:" + path, result.returncode in (0, 1)
          and (result.returncode == 0) == expected)
tracked = set(subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], timeout=10)
              .decode().split("\0"))
internal = {"onboarding/" + name for name in
            ("CONTEXT_PACKET.md", "ORIGINAL_RECHECK.json", "POLICY_HASHES.json",
             "SOURCE_MANIFEST.json", "STATUS.md", "TASK_ASSESSMENT.md")}
check("internal-onboarding-excluded-from-index", not (tracked & internal))
print(json.dumps({"status": "PASS", "checks": results}, indent=2))
