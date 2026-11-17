"""For each hand-labeled wrong answer, did the wrong keyword appear in the bot's own tool output?

usage: python eval/tool_origin.py ANSWERS_DIR > eval/tool-origin.txt
ANSWERS_DIR holds score.json and each <key>.sse.txt (the raw streams are not redistributed; eval/tool-origin.txt
is this script's output).
Also reports whether any tool output contained the method's Python source (`def <method>`).
"""
import json, re, sys
from pathlib import Path

ask = Path(sys.argv[1])
rows = [r for r in json.loads((ask / 'score.json').read_text(encoding='utf-8'))['rows'] if r['label'] == 'wrong']
repeated = invented = with_def = 0
for r in rows:
    outs = []
    for line in (ask / f"{r['key']}.sse.txt").read_text(encoding='utf-8').splitlines():
        if line.startswith('data: ') and line[6:] != '[DONE]':
            d = json.loads(line[6:])
            if d.get('type') == 'tool-output-available':
                outs.append(json.dumps(d.get('output')))
    o = ' '.join(outs)
    m = re.search(r'`(\w+)` is not a parameter', r['hints'][0])
    bad = m.group(1) if m else None
    method = r['key'].split('__')[-1]
    in_out = bool(bad) and (bad + '=') in o
    has_def = ('def ' + method) in o
    repeated += in_out; invented += not in_out; with_def += has_def
    print(f"{r['key']}\tbad={bad}\tin_tool_output={in_out}\tdef_in_tool_output={has_def}")
print(f"\nwrong answers: {len(rows)}  repeated from tool output: {repeated}  not in any tool output: {invented}  "
      f"tool output with method source: {with_def}")
