"""Run with a JSONL path, or omit it to summarize all continuous skill runs."""
import json
import sys
from pathlib import Path

from typesafe_mario.skill_analysis import analyze, write_summary

paths = [Path(p) for p in sys.argv[1:]] or sorted(Path('artifacts/continuous-skills').glob('*.jsonl'))
for path in paths:
    summary = analyze(path)
    write_summary(path)
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_hashes'}, ensure_ascii=False))
