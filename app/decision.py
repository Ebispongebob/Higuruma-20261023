"""确定性检查只处理可解析的事实；不清楚的事实留给复核。"""
import re
from datetime import date, timedelta
from decimal import Decimal
from app.models import decide


def result(status, reason):
    return {'status': status, 'reason': reason, 'method': 'deterministic', 'score': None, 'duration_ms': 0}


def procurement(rule, text):
    if rule.get('check') not in ('purchase_approval','purchase_fields'):
        return None
    if '采购' not in text:
        return result('not_applicable', '待审核文本没有采购业务关系，采购规则不适用。')
    amounts = re.findall(r'(?:采购金额|金额)\s*[：:]?\s*([\d,]+(?:\.\d+)?)\s*(万)?\s*元?', text)
    values = {Decimal(n.replace(',','')) * (10000 if unit else 1) for n,unit in amounts}
    if len(values) > 1:
        return result('insufficient', '原文存在多个金额，需确认适用金额。')
    if rule['check'] == 'purchase_fields':
        missing = []
        if not re.search(r'供应商\s*[：:]\s*[^\s\n，。]+', text):
            missing.append('供应商')
        if not values:
            missing.append('金额')
        dates = re.findall(r'交付日期\s*[：:]\s*(\d{4}-\d{2}-\d{2})', text)
        if not dates:
            missing.append('交付日期')
        else:
            try:
                for d in dates: date.fromisoformat(d)
            except ValueError:
                return result('violation', '交付日期不是有效日期。')
        if missing:
            return result('violation', '完整解析后未找到有效必填字段：'+ '、'.join(missing)+'。')
        return result('compliant', '供应商、金额和有效交付日期均已填写。')
    if not values:
        return result('insufficient','缺少可确定的采购金额，无法判断审批门槛。')
    if next(iter(values)) <= Decimal(rule.get('threshold_amount','100000')):
        return result('not_applicable','金额未超过该版本规则的审批门槛。')
    approved = re.search(r'已获财务总监审批|财务总监[：:](?:审批)?同意|财务总监审批(?:已)?通过',text)
    rejected = re.search(r'未获财务总监审批|财务总监.{0,8}拒绝|审批被拒',text)
    if approved and rejected:
        return result('insufficient','正文与附件的审批事实冲突，需要人工确认先后关系。')
    if not re.search(r'审批|授权|财务总监|总经理', text):
        return result('insufficient', '完整原文没有交代审批事实，无法判断是否获得所需审批。')
    if re.search(r'审批材料(?:没有|未)提供|没有交代审批|审批情况不明', text) and not approved and not rejected:
        return result('insufficient', '原文明示审批证明材料未提供，不能推断未获审批。')
    return None


def probation(rule, text):
    if rule.get('check') != 'labor_probation' or '劳动合同' not in text:
        return None
    duration = re.search(r'合同期限[：:]\s*(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})', text)
    trial = re.search(r'试用期[：:]\s*([零一二三四五六七八九十\d]+)个?月', text)
    if not duration or not trial:
        return None
    try:
        start, end = date.fromisoformat(duration[1]), date.fromisoformat(duration[2]) + timedelta(days=1)
        if end <= start or start.day != end.day: return None
        months = (end.year-start.year)*12+end.month-start.month
        number=trial[1]; actual=int(number) if number.isdigit() else {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(number)
        if actual is None: return None
    except ValueError:
        return result('insufficient','合同期限不是有效日期，需核对。')
    allowed=0 if months<3 else 1 if months<12 else 2 if months<36 else 6
    if actual>allowed:
        return result('violation',f'合同期限为 {months} 个月，试用期为 {actual} 个月，超过本条规定的 {allowed} 个月上限。')
    # 未超过上限还不能证明同一法条的其他条件均已满足。
    return None


async def evaluate(config, rule, text, agent_id):
    deterministic = procurement(rule, text) or probation(rule, text)
    if deterministic:
        return deterministic
    instructions = rule['text']+'\n适用范围：'+rule.get('scope','')+'\n例外：'+rule.get('exceptions','')+'\n需要的证明：'+rule.get('evidence_required','')
    verdict = await decide(config, instructions, text, agent_id)
    verdict['method'] = 'model'
    verdict['reason'] = {
        'compliant': '模型判断本条要求已满足，请结合引用原文核对。',
        'violation': '模型发现本条要求可能被违反，请核对原文和制度条款。',
        'insufficient': '材料不足、存在冲突或模型分数不足，需要人工复核。',
        'not_applicable': '模型判断本条适用条件未触发。',
    }[verdict['status']]
    return verdict
