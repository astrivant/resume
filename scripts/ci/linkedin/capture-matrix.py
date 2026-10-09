"""
Export the validated frozen plan's worker count to the GitHub Actions matrix.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from resumeme.linkedin.capture.shards import load_capture_plan

plan = load_capture_plan(Path(".cache/capture/plan.json"))

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"count={plan.shard_count}\n")
    output.write(f"shards={json.dumps(list(range(1, plan.shard_count + 1)))}\n")
