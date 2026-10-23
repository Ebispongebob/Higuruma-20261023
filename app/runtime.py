"""固定审核流程；保存规则快照、配置版本和每一步结果。"""
import asyncio
import copy
from collections import Counter
from app import store
from app.decision import evaluate
from app.evidence import citations, collect, full_text
from app.models import ModelFailure, config_version

WORKERS = asyncio.Semaphore(1)
TASKS = set()


def conclusion(findings, complete):
    statuses = [x.get('review', {}).get('status', x['status']) for x in findings]
    if 'violation' in statuses:
        return '发现不符合项'
    if not complete or not statuses or 'insufficient' in statuses or 'failed' in statuses or all(x == 'not_applicable' for x in statuses):
        return '需人工复核'
    return '在本次审核范围内符合'


def launch(agent, documents, rules, business_date):
    audit = {'id': store.uid(), 'agent_id': agent['id'], 'agent_name': agent['name'], 'created_at': store.now(),
             'status': 'queued', 'conclusion': '需人工复核', 'business_date': business_date,
             'documents': documents, 'rules': copy.deepcopy(rules), 'config': copy.deepcopy(agent['config']),
             'config_version': config_version(agent['config']), 'pipeline_version': '1',
             'demo': any(r.get('demo') and not r.get('confirmed') for r in rules),
             'findings': [], 'events': [], 'total': len(rules)}
    store.save_audit(audit)
    task = asyncio.create_task(run(audit))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return audit


async def run(audit):
    async with WORKERS:
        audit['status'] = 'running'
        store.save_audit(audit)
        blocks = collect(audit['documents'])
        text = full_text(blocks)
        outage = False
        try:
            for rule in audit['rules']:
                evidence = citations(rule, blocks)
                try:
                    if outage:
                        raise ModelFailure('前序模型调用失败，本条未执行；请重试审核')
                    finding = await evaluate(audit['config'], rule, text, audit['agent_id'])
                except ModelFailure as e:
                    finding = {'status': 'failed', 'reason': str(e), 'method': 'model', 'score': None}
                    outage = True
                finding.update({'rule_id': rule['id'], 'rule_version': rule['version'], 'rule_title': rule['title'],
                                'rule_text': rule['text'], 'rule_location': rule['source_location'], 'evidence': evidence})
                audit['findings'].append(finding)
                audit['events'].append({'time': store.now(), 'rule_id': rule['id'], 'status': finding['status'], 'method': finding['method']})
                audit['conclusion'] = conclusion(audit['findings'], False)
                store.save_audit(audit)
            audit['status'] = 'partial' if outage else 'completed'
            audit['conclusion'] = conclusion(audit['findings'], not outage)
            audit['finished_at'] = store.now()
            audit['counts'] = dict(Counter(f['status'] for f in audit['findings']))
            store.save_audit(audit)
        except asyncio.CancelledError:
            audit['status'] = 'interrupted'
            audit['error'] = '审核已中断，可重新发起'
            audit['conclusion'] = conclusion(audit['findings'], False)
            store.save_audit(audit)
            raise
        except Exception:
            audit['status'] = 'failed'
            audit['error'] = '审核执行失败，已完成结果保留，请重新发起'
            audit['conclusion'] = conclusion(audit['findings'], False)
            store.save_audit(audit)
