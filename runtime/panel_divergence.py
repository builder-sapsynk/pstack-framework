#!/usr/bin/env python3
"""Check that panel candidates were briefed independently and returned distinct shapes."""
import json
from pathlib import Path
import re

# Whole-shape starting points for design candidates; seat N takes entry N.
LENSES = {'architect': ('data-model-first: one typed structure owns the decision',
                        'boundary-first: move the decision to the layer that already knows the answer',
                        'subtraction-first: delete or narrow the surface until the problem disappears',
                        'table-driven: rules as data with one small interpreter')}
MAX_SIMILARITY = 0.6
LENS = re.compile(r'^Lens:\s*(\S.*)$', re.MULTILINE)
SHAPE = re.compile(r'^(?:Data\s+)?Shape:\s*(\S.*)$', re.MULTILINE | re.IGNORECASE)
WORD = re.compile(r'[a-z_][a-z0-9_]{3,}')


def normal(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.lower()))


def similarity(left, right):
    """Jaccard overlap of the two answers' vocabularies."""
    a, b = set(WORD.findall(left.lower())), set(WORD.findall(right.lower()))
    return round(len(a & b) / len(a | b), 3) if a | b else 1.0


def check(candidates, limit=MAX_SIMILARITY):
    """`candidates` are dicts with task, state, session, brief and message. Returns the verdict."""
    problems = []
    if len(candidates) < 2:
        problems.append('a divergence check needs at least two candidates')
    for candidate in candidates:
        task = candidate['task']
        if candidate.get('state') != 'succeeded':
            problems.append(f'{task}: state {candidate.get("state")} is not a candidate')
        lens = LENS.search(candidate['brief'])
        candidate['lens'] = normal(lens.group(1)) if lens else None
        if not lens:
            problems.append(f'{task}: brief has no `Lens:` line, so nothing made this candidate differ')
        shape = SHAPE.search(candidate['message'])
        candidate['shape'] = normal(shape.group(1)) if shape else None
        if not shape:
            problems.append(f'{task}: answer has no `Shape:` line')
        for other in candidates:
            if other is not candidate and re.search(r'(?<![\w.-])' + re.escape(other['task']) + r'(?![\w-])', candidate['brief']):
                problems.append(f'{task}: brief names candidate {other["task"]}; candidates must not see each other')
            leaked = [line for line in map(str.strip, other['message'].splitlines())
                      if other is not candidate and len(line) >= 40 and line in candidate['brief']]
            if leaked:
                problems.append(f'{task}: brief quotes the answer of {other["task"]}; candidates must not see each other')
    pairs = []
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            names = f'{left["task"]} and {right["task"]}'
            score = similarity(left['message'], right['message'])
            pairs.append({'a': left['task'], 'b': right['task'], 'similarity': score})
            if left['lens'] and left['lens'] == right['lens']:
                problems.append(f'{names}: same lens')
            if left.get('session') and left.get('session') == right.get('session'):
                problems.append(f'{names}: same session')
            if left['shape'] and left['shape'] == right['shape']:
                problems.append(f'{names}: same declared shape')
            elif score > limit:
                problems.append(f'{names}: answers overlap {score} > {limit}')
    return {'distinct': not problems, 'max_similarity': limit, 'pairs': pairs, 'problems': problems,
            'candidates': [{key: c.get(key) for key in ('task', 'lens', 'shape')} for c in candidates]}


def load(project, task):
    run = Path(project) / '.pstack/runs' / task
    status = json.loads((run / 'status.json').read_text())
    message = run / 'last-message.txt'
    return {'task': task, 'state': status.get('state'), 'session': status.get('session_id'),
            'brief': (run / 'brief.md').read_text(), 'message': message.read_text() if message.is_file() else ''}


def arguments(sub):
    sub.add_argument('tasks', nargs='+', help='Task ids of the finished candidates')
    sub.add_argument('--max-similarity', type=float, default=MAX_SIMILARITY)


def main(args, project):
    verdict = check([load(project, task) for task in args.tasks], args.max_similarity)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict['distinct'] else 1
