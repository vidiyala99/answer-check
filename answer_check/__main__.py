"""CLI: `python -m answer_check index <sdk_src> -o index.json` and `python -m answer_check check --index index.json FILE`.

check exits 0 when every checked call is ok (or not-checked), 1 when any call is wrong-arg / unknown-method.
FILE is a Markdown answer, or a saved JSON record with an "answer" field.
"""
import argparse
import json
import sys
from pathlib import Path

from .check import check_answer
from .sigindex import build_index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='answer_check')
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('index', help='build a signature index from SDK source (static, nothing is imported)')
    i.add_argument('sdk_src')
    i.add_argument('--version')
    i.add_argument('-o', '--output', required=True)
    c = sub.add_parser('check', help='check SDK calls in an answer')
    c.add_argument('--index', required=True)
    c.add_argument('file')
    args = ap.parse_args(argv)

    if args.cmd == 'index':
        idx = build_index(args.sdk_src, version=args.version)
        Path(args.output).write_text(json.dumps(idx, indent=1), encoding='utf-8')
        n = sum(len(v['methods']) for v in idx['classes'].values())
        print(f"indexed {len(idx['classes'])} classes, {n} methods; skipped {len(idx['skipped_files'])} files",
              file=sys.stderr)
        return 0

    idx = json.loads(Path(args.index).read_text(encoding='utf-8'))
    raw = Path(args.file).read_text(encoding='utf-8')
    text = raw
    if args.file.endswith('.json'):
        text = json.loads(raw).get('answer', '')
    result = check_answer(text, idx)
    sys.stdout.write(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
