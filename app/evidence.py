"""遍历全部生效规则。模型看到完整原文，引用来自解析结果。"""
import re
from datetime import date


def select_rules(rules, business_date, allow_demo=False):
    date.fromisoformat(business_date)
    groups = {}
    for rule in rules:
        if not rule.get('confirmed') and not (allow_demo and rule.get('demo')):
            continue
        if rule['effective_from'] > business_date or (rule.get('effective_to') and rule['effective_to'] <= business_date):
            continue
        old = groups.get(rule['id'])
        if old is None or old['effective_from'] < rule['effective_from']:
            groups[rule['id']] = rule
    return list(groups.values())


def collect(documents):
    blocks = []
    for document in documents:
        for block in document['blocks']:
            blocks.append({**block, 'document_id': document['id'], 'document_name': document['name'],
                           'ref': document['id']+':'+block['id']})
    return blocks


def full_text(blocks):
    return '\n'.join(f"{b['location']}：{b['text']}" for b in blocks)


def citations(rule, blocks):
    terms = set(re.findall(r'[\u4e00-\u9fff]{2,}', rule['text']))
    grams = {term[i:i+2] for term in terms for i in range(len(term)-1)}
    ranked = [(sum(gram in b['text'] for gram in grams), b) for b in blocks]
    relevant = [b for score,b in ranked if score > 0]
    # 返回全部命中，不用前几条检索结果代表全文不存在其他证据。
    return relevant or blocks
