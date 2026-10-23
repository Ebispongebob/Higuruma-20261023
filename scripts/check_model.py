"""真实决策接口端到端检查，不使用替身服务。"""
import asyncio
import json
import statistics
from pathlib import Path
from app.models import DEFAULTS, ModelFailure, decide, discover_local

async def main():
    discover_local()
    rows = json.loads(Path('fixtures/model_samples.json').read_text())
    results = []
    for row in rows:
        try:
            result = await decide(DEFAULTS['local'], row['rule'], row['text'])
            results.append({'id': row['id'], 'expected': row['expected'], **result, 'passed': result['status'] == row['expected']})
        except ModelFailure as e:
            results.append({'id': row['id'], 'passed': False, 'error': str(e)})
    report = {'dataset': '程序构造的采购调试样例，不是独立人工验收', 'passed': sum(x['passed'] for x in results), 'total': len(rows), 'results': results}
    Path('reports/model-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'通过':report['passed'],'总数':len(rows),'平均耗时毫秒':round(statistics.mean(x.get('duration_ms',0) for x in results))},ensure_ascii=False))
    for r in results:
        if not r['passed']: print(r['id'],r.get('expected'),r.get('status'),r.get('error',''))
    return 0 if report['passed'] == len(rows) else 1

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
