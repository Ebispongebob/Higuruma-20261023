"""法条来源可追溯的端到端效果检查；期望值是程序构造，未经人工法律审核。"""
import json
import os
import time
from pathlib import Path

import httpx

BASE = os.getenv('E2E_URL', 'http://127.0.0.1:8766')


def main():
    corpus = json.loads(Path('fixtures/corpus/labor-contract-law.json').read_text())
    scenarios = json.loads(Path('fixtures/law_scenarios.json').read_text())
    results = []
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as client:
        def call(method, path, expected=200, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f'业务接口返回 HTTP {response.status_code}')
            return response.json()
        agents = {}
        for number in sorted({s['article'] for s in scenarios}):
            article = next(a for a in corpus['articles'] if a['articleNumber'] == number)
            agent = call('POST', '/api/agents', 201, json={'name': f'法律效果检查·{article["displayNumber"]}'})
            agent_id = agent['id']
            text = article['text'].replace('\n', ' ')
            standard = call('POST', f'/api/agents/{agent_id}/documents?kind=standard', 201,
                            files={'file': ('劳动合同法条文.txt', text.encode())})
            call('POST', f'/api/agents/{agent_id}/rules', 201, json={
                'id': article['id'], 'title': corpus['title'] + article['displayNumber'],
                'text': text, 'scope': '劳动合同与用工关系', 'version': corpus['promulgationDate'],
                'effective_from': corpus['effectiveDate'], 'document_id': standard['id'],
                'block_id': standard['blocks'][0]['id'], 'source_quote': text,
                'check': 'labor_probation' if number == 19 else 'semantic',
                'confirmed': True,
            })
            agents[number] = agent_id
        for scenario in scenarios:
            agent_id = agents[scenario['article']]
            document = call('POST', f'/api/agents/{agent_id}/documents', 201,
                            files={'file': (scenario['id'] + '.txt', scenario['text'].encode())})
            start = time.monotonic()
            audit = call('POST', f'/api/agents/{agent_id}/audits', 202, json={
                'document_ids': [document['id']], 'business_date': '2026-11-01',
            })
            deadline = start + 120
            while audit['status'] in ('queued', 'running') and time.monotonic() < deadline:
                time.sleep(.15)
                audit = call('GET', f'/api/agents/{agent_id}/audits/{audit["id"]}')
            finding = audit['findings'][0] if audit['findings'] else {}
            citations_valid = all(
                any(b['id'] == e['id'] and b['text'] == e['text'] for b in document['blocks'])
                and e['document_id'] == document['id'] for e in finding.get('evidence', [])
            ) and bool(finding.get('evidence'))
            result = {
                'id': scenario['id'], 'article': scenario['article'], 'expected': scenario['expected'],
                'status': finding.get('status'), 'method': finding.get('method'),
                'score': finding.get('score'), 'probabilities': finding.get('probabilities'),
                'citations_valid': citations_valid, 'audit_status': audit['status'],
                'conclusion': audit['conclusion'], 'seconds': round(time.monotonic() - start, 2),
                'passed': audit['status'] == 'completed' and finding.get('status') == scenario['expected'] and citations_valid,
            }
            results.append(result)
            print(scenario['id'], '通过' if result['passed'] else '未通过', flush=True)
    report = {
        'source': json.loads(Path('fixtures/corpus/source.json').read_text()),
        'scope': '从实际制度上传、规则确认、文件上传到真实本地模型与报告的全流程。期望分类为程序构造，未经人工法律审核。',
        'passed': sum(r['passed'] for r in results), 'total': len(results), 'results': results,
    }
    Path('reports/law-quality.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('法律效果检查：', report['passed'], '/', report['total'])
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, RuntimeError) as exc:
        print('法律效果检查未完成：', type(exc).__name__)
        raise SystemExit(1)
