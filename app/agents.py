"""规则保存原文引用；演示规则不等同于业务人工确认。"""
import copy
import json
from pathlib import Path
from app import store
from app.models import DEFAULTS


def create_agent(name, description, config=None):
    agent = {'id': store.uid(), 'name': name, 'description': description, 'created_at': store.now(),
             'config': copy.deepcopy(config or DEFAULTS['local']), 'rules': [], 'demo': False}
    store.save_agent(agent)
    return agent


def seed():
    if store.agents():
        return
    law = json.loads(Path('fixtures/corpus/labor-contract-law.json').read_text())
    source = json.loads(Path('fixtures/corpus/source.json').read_text())
    legal = create_agent('劳动合同审核', '检查劳动合同中的用工约定，逐条关联法律依据。')
    legal['demo'] = True
    legal['source'] = source
    selected = set(range(8, 28)) | set(range(30, 40))
    blocks = [{'id': a['id'], 'text': a['text'], 'location': a['displayNumber']} for a in law['articles'] if a['articleNumber'] in selected]
    document = store.save_document(legal['id'], {'name': law['title'], 'blocks': blocks, 'complete': True, 'kind': 'standard', 'source': source}, json.dumps(law, ensure_ascii=False).encode())
    for a in law['articles']:
        if a['articleNumber'] in selected:
            legal['rules'].append({'id': a['id'], 'title': law['title']+' '+a['displayNumber'], 'text': a['text'],
                'scope': '劳动合同与用工关系', 'exceptions': '', 'evidence_required': '合同约定及相应事实证明',
                'effective_from': law['effectiveDate'], 'effective_to': None, 'version': law['promulgationDate'],
                'document_id': document['id'], 'block_id': a['id'], 'source_quote': a['text'], 'source_location': a['displayNumber'],
                'confirmed': False, 'demo': True, 'check': 'labor_probation' if a['articleNumber'] == 19 else 'semantic'})
    store.save_agent(legal)
    purchase = create_agent('采购文件审核', '检查采购审批、金额边界与必填信息。')
    purchase['demo'] = True
    texts = ['采购金额超过10万元，必须有财务总监审批；紧急采购允许以总经理书面授权替代。', '采购文件必须填写供应商、金额和交付日期。']
    document = store.save_document(purchase['id'], {'name': '采购演示制度', 'kind': 'standard', 'complete': True,
        'blocks': [{'id': f'p{i+1}', 'text': t, 'location': f'第 {i+1} 条'} for i,t in enumerate(texts)]}, '\n'.join(texts).encode())
    for i, txt in enumerate(texts):
        purchase['rules'].append({'id': f'R{i+1}', 'title': ['采购审批','采购必填信息'][i], 'text': txt, 'scope': '采购',
            'exceptions': '紧急采购有总经理书面授权' if i == 0 else '', 'evidence_required': '审批记录及采购文件',
            'effective_from': '2020-01-01', 'effective_to': None, 'version': '演示-v1', 'document_id': document['id'],
            'block_id': f'p{i+1}', 'source_quote': txt, 'source_location': f'第 {i+1} 条', 'confirmed': False, 'demo': True,
            'check': 'purchase_approval' if i == 0 else 'purchase_fields', 'threshold_amount': '100000'})
    store.save_agent(purchase)
