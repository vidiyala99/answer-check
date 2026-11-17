"""Score answer_check against hand labels.

usage: python eval/score_v1.py ANSWERS_DIR eval/hand-labels.json OUT.json
ANSWERS_DIR holds one <key>.json per question with an "answer" field (the bot's Markdown reply).
The bot replies themselves are not redistributed in this repo; eval/score.json is the result of this script.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from answer_check.check import check_answer  # noqa: E402

ask, labels_path, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
labels = json.loads(Path(labels_path).read_text(encoding='utf-8')); labels.pop('_note', None)
index = json.loads((Path(__file__).resolve().parents[1] / 'data/index-python-10.9.0.json').read_text(encoding='utf-8'))
rows, tally = [], {'caught': 0, 'missed': 0, 'false_flag': 0, 'clean_pass': 0}
for key, lab in sorted(labels.items()):
    rec = json.loads((ask / f'{key}.json').read_text(encoding='utf-8'))
    res = check_answer(rec['answer'], index)
    flagged = not res['ok']
    wrong = lab['label'] == 'wrong'
    outcome = ('caught' if flagged else 'missed') if wrong else ('false_flag' if flagged else 'clean_pass')
    tally[outcome] += 1
    rows.append({'key': key, 'label': lab['label'], 'flagged': flagged, 'outcome': outcome,
                 'calls': [(c['call'], c['verdict']) for c in res['calls']], 'hints': res['repair_hints']})
summary = {'n': len(rows), **tally, 'wrong_by_hand': tally['caught'] + tally['missed'],
           'drift_wrong': sum(r['label'] == 'wrong' for r in rows if r['key'].startswith('drift')),
           'clean_wrong': sum(r['label'] == 'wrong' for r in rows if r['key'].startswith('clean'))}
Path(out).write_text(json.dumps({'summary': summary, 'rows': rows}, indent=1), encoding='utf-8')
print(json.dumps(summary))
for r in rows:
    if r['outcome'] in ('missed', 'false_flag') or r['label'] == 'wrong':
        print(r['outcome'], r['key'], r['hints'][:1])
