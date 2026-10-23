"""生成可公开复现的演示输入，不冒充独立人工标注。"""
import json
from pathlib import Path

RULE = '采购金额超过10万元，必须有财务总监审批；紧急采购允许以总经理书面授权替代。'
rows = []
variants = [
 ('已获财务总监审批，并附签署记录。', 'compliant'),
 ('仅部门经理审批，未获财务总监审批，非紧急采购。', 'violation'),
 ('审批材料没有提供。', 'insufficient'),
 ('本次为紧急采购，已取得总经理书面授权。', 'compliant'),
]
for amount in [110000,150000,200000,300000,500000]:
 for suffix,expected in variants:
  rows.append({'id':f'M{len(rows)+1:02}', 'rule':RULE,'text':f'采购申请：金额{amount}元，供应商甲公司，交付日期2026-11-01。'+suffix,'expected':expected,'origin':'程序构造，待人工确认'})
Path('fixtures/model_samples.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
Path('fixtures/purchase.txt').write_text('采购申请\n供应商：甲公司\n金额：150000元\n交付日期：2026-11-01\n仅部门经理审批，未获财务总监审批，非紧急采购。\n')
Path('fixtures/employment.txt').write_text('劳动合同\n甲方：示例科技有限公司\n乙方：张某\n合同期限：2026-11-01至2027-10-31，为期一年。\n试用期：六个月。\n双方约定劳动者需缴纳入职押金5000元，离职后退还。\n乙方主动辞职须支付违约金50000元，不涉及专项培训或竞业限制。\n')
