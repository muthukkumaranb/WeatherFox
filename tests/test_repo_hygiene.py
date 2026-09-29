import subprocess
import os
import re
from pathlib import Path

def test_repo_hygiene():
    # 1. splits/split.json must exist
    assert Path("splits/split.json").exists(), "splits/split.json is missing!"

    # 2. .gitignore must not have NUL bytes
    gitignore_path = Path(".gitignore")
    if gitignore_path.exists():
        with open(gitignore_path, "rb") as f:
            content = f.read()
            assert b'\x00' not in content, ".gitignore contains NUL bytes!"

    # 3. No tracked file > 5MB
    # We use git ls-files to get all tracked files
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    tracked_files = result.stdout.strip().split("\n")
    
    for f in tracked_files:
        if not f:
            continue
        p = Path(f)
        if p.exists():
            size_mb = p.stat().st_size / (1024 * 1024)
            assert size_mb <= 5.0, f"Tracked file {f} is larger than 5 MB ({size_mb:.2f} MB)"

    # 4. No tracked path matches prompt|PLAN|HANDOVER|copilot-instructions
    pattern = re.compile(r"prompt|PLAN|HANDOVER|copilot-instructions", re.IGNORECASE)
    for f in tracked_files:
        if not f:
            continue
        assert not pattern.search(f), f"Tracked file {f} violates prompt/plan naming rules"

