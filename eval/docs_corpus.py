"""Run answer_check over every Python block in the saved WorkOS docs pages.

usage: python eval/docs_corpus.py PAGES_DIR data/index-python-10.9.0.json OUT_DIR
Writes OUT_DIR/corpus.json (every flagged call, with page URL) and OUT_DIR/corpus-summary.txt.
Pages were fetched 2026-11-16 23:35 PST from https://workos.com/docs/<path>.md ('__' = '/').
"""
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from answer_check.check import check_answer  # noqa: E402


def main(pages_dir: str, index_path: str, out_dir: str) -> None:
    index = json.loads(Path(index_path).read_text(encoding='utf-8'))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    verdicts = collections.Counter()
    blocks = parsed = syntax_err = 0
    flagged = []
    manifest = hashlib.sha256()
    for pf in sorted(Path(pages_dir).glob('*.md')):
        raw = pf.read_bytes()
        manifest.update(pf.name.encode() + b'\0' + hashlib.sha256(raw).digest())
        url = 'https://workos.com/docs/' + pf.stem.replace('__', '/')
        res = check_answer(raw.decode('utf-8', errors='replace'), index)
        for b in res['blocks']:
            blocks += 1
            parsed += b['status'] == 'parsed'
            syntax_err += b['status'] == 'syntax-error'
        for c in res['calls']:
            verdicts[c['verdict']] += 1
            if c['verdict'] in ('wrong-arg', 'unknown-method'):
                flagged.append({'url': url, **c})

    pages = {f['url'] for f in flagged}
    wrong = [f for f in flagged if f['verdict'] == 'wrong-arg']
    methods = {f['call'] for f in wrong}
    id_calls = [f for f in wrong if any(p.get('keyword') == 'id_' for p in f['problems'])]
    kinds = collections.Counter(p['kind'] for f in flagged for p in f['problems'])
    by_call = collections.Counter((f['call'], f['verdict']) for f in flagged)

    lines = [
        f"sdk: workos-python {index.get('sdk_version')}",
        f"pages: {len(list(Path(pages_dir).glob('*.md')))}  manifest sha256: {manifest.hexdigest()}",
        f"python blocks: {blocks}  parsed: {parsed}  syntax-error: {syntax_err}",
        f"sdk calls found: {sum(verdicts.values())}  " + '  '.join(f'{k}: {v}' for k, v in sorted(verdicts.items())),
        f"flagged calls: {len(flagged)} on {len(pages)} pages",
        f"wrong-arg calls: {len(wrong)} across {len(methods)} methods on {len({f['url'] for f in wrong})} pages",
        f"wrong-arg calls using id_: {len(id_calls)}",
        'problem kinds: ' + '  '.join(f'{k}: {v}' for k, v in sorted(kinds.items())),
        '',
        'count  verdict         call',
    ]
    lines += [f'{n:5}  {v:14}  {c}' for (c, v), n in by_call.most_common()]
    (out / 'corpus-summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (out / 'corpus.json').write_text(json.dumps(flagged, indent=1, ensure_ascii=False), encoding='utf-8')
    print('\n'.join(lines[:9]))


if __name__ == '__main__':
    main(*sys.argv[1:4])
