Read .github/copilot-instructions.md and skyguard/contract.py first, and follow them exactly.

Task: three cleanups, then run pytest on a fresh clone and push. No new features.

1. CONFIG: config/skyguard.toml, section [split]
   - Delete the keys test_time_start and val_time_start, and the stray line "genuine_events = []".
   - Do not add or rename anything else. Keep the station-fraction and year keys that describe the rule:
       train = 2023 train stations
       validation = 15 % held-out stations in 2023
       test = all of 2024 + 15 % unseen stations
     Keep the comment in the file that states this rule, and make sure skyguard/data/split.py's docstring says the same.
   - Search code, tests and docs for any use of the deleted keys and remove it.

2. FAKE DETECTOR: skyguard/fake_score.py
   - Delete any branch that handles an empty or missing list of rows for the target. An empty target window must
     raise ContractError, and the window check in contract.py (check_window / validate_window, whichever name
     exists) already enforces that. Do not re-implement the check inside the fake.
   - Keep the branch for a target row whose readings are all null (comms gap). That is a valid row, not an empty window.
   - Every value the fake returns must pass validate_verdict. Add a parametrised test that runs the fake through
     these scenarios and asserts validate_verdict passes on each result: normal reading, lone spike with calm
     neighbours, hot everywhere (genuine event), extreme reading with no neighbours, dew point above temperature,
     all-null readings. Add a test that an empty target window raises ContractError.

3. ONE SCHEMA FOLDER
   - Keep exactly one schema folder: skyguard/schemas/. Move the three schema files there with git mv, then delete
     the top-level schemas/ folder.
   - Update contract.py so SCHEMA_DIR points at skyguard/schemas/ (relative to the package file, no absolute paths).
   - If there is a pyproject.toml or setup file, make sure the JSON files are included as package data.
   - Update README.md and .github/copilot-instructions.md so they mention only skyguard/schemas/.
   - Verify with: grep -rn "schemas" . --include="*.py" --include="*.md" --include="*.toml"
     Every hit must refer to skyguard/schemas/ (or the word in ordinary prose), and no top-level schemas/ path
     may remain anywhere, including tests and examples.

4. PROVE IT ON A FRESH CLONE, THEN PUSH
   - Commit locally. In a temporary directory run: git clone <this repo> fresh && cd fresh &&
     python -m venv .venv && pip install -r requirements.txt && python -m pytest -q.
     All tests must pass, including the schema tests, so a missing schema file on the fresh clone is caught.
   - Only if that passes: push to my current branch with a normal push (no force). If anything fails, do not push;
     fix it and re-run the fresh-clone check.

Done when: the fresh-clone pytest passes, git ls-files shows the schemas only under skyguard/schemas/,
no deleted config key remains anywhere, and the push succeeded.
Finish with a short report: files changed, the test count and result on the fresh clone, the commit hash, and
anything ambiguous that you decided.