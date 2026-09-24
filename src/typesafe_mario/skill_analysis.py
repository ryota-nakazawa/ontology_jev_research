"""Summaries describe observed outcomes, never infer that an ontology caused them."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median


def analyze(path):
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    frames = [r for r in events if r['event'] == 'controller_frame']
    responses = [r for r in events if r['event'] == 'response']
    ends = [r for r in events if r['event'] == 'episode_end']
    skills = defaultdict(Counter)
    for r in events:
        if r['event'] == 'skill_result':
            result = r['result']
            skills[result['skill']][result['status'] + ':' + result['reason']] += 1
    count = Counter(r['event'] for r in events)
    latency = [r['latency_ms'] for r in responses]
    return {
        'file': str(Path(path).resolve()),
        'complete': bool(ends),
        'end_reason': ends[-1]['reason'] if ends else None,
        'best_x': ends[-1]['best_x'] if ends else None,
        'frames': len(frames), 'requests': count['request'],
        'responses': len(responses), 'response_rejections': count['response_rejected'],
        'rejection_reasons': dict(Counter(r['reason'] for r in events if r['event'] == 'response_rejected')),
        'request_errors': count['request_error'], 'abandoned_requests': count['request_abandoned'],
        'frames_with_request_in_flight': sum(r['pending_request'] is not None for r in frames),
        'control_sources': dict(Counter(r['source'] for r in frames)),
        'local_phases': dict(Counter(r['phase'] for r in frames if r['source'] == 'local_handoff')),
        'latency_ms_median': round(median(latency), 1) if latency else None,
        'skills': {k: dict(v) for k, v in skills.items()},
        'routes': dict(Counter(r.get('route') for r in responses)),
        'source_hashes': events[0].get('source_hashes', {}),
    }


def write_summary(path):
    summary = analyze(path)
    output = Path(path).with_suffix('.summary.json')
    output.write_text(json.dumps(summary, indent=2))
    return output
