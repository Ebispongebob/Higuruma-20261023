import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agents, runtime, store
from app.documents import DocumentFailure, MAX_BYTES, parse_document
from app.evidence import collect, full_text, select_rules
from app.models import DEFAULTS, LABELS, SECRETS, ModelFailure, decide, discover_local, validate_config


@asynccontextmanager
async def lifespan(app):
    discover_local()
    store.initialize()
    agents.seed()
    yield
    for task in list(runtime.TASKS): task.cancel()
    if runtime.TASKS: await asyncio.gather(*runtime.TASKS, return_exceptions=True)


app = FastAPI(title='Higuruma 审核工作台', lifespan=lifespan)
from starlette.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])


@app.middleware('http')
async def local_boundary(request: Request, call_next):
    # 本地工具不接受其他网站发起的写请求，避免浏览器跨站访问本地凭据。
    origin = request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail': '不接受跨站写入请求'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


# 不返回 Pydantic 的 input，配置请求可能带有密钥。
from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({'detail': '请求字段不完整或格式错误'}, status_code=422)


def require_agent(agent_id):
    agent = store.get_agent(agent_id)
    if not agent: raise HTTPException(404, 'Agent 不存在')
    return agent


def public_agent(agent):
    return {**agent, 'key_configured': bool(SECRETS.get(agent['id']) or (agent['config']['url'] == DEFAULTS[agent['config']['provider']]['url'] and SECRETS.get(agent['config']['provider'])))}


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)

class ConfigInput(BaseModel):
    provider: Literal['local','commandcode']
    url: str = Field(max_length=1000)
    model: str = Field(min_length=1, max_length=160)
    timeout: float = Field(default=45, ge=1, le=120)
    threshold: float = Field(default=.65, ge=0, le=1)
    api_key: str | None = Field(default=None, max_length=4096, repr=False)

class RuleInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=6000)
    scope: str = Field(default='', max_length=300)
    exceptions: str = Field(default='', max_length=1000)
    evidence_required: str = Field(default='', max_length=1000)
    effective_from: date
    effective_to: date | None = None
    version: str = Field(min_length=1, max_length=100)
    document_id: str
    block_id: str
    source_quote: str = Field(min_length=1, max_length=6000)
    confirmed: bool = False
    check: Literal['semantic','purchase_approval','purchase_fields','labor_probation'] = 'semantic'
    threshold_amount: str = Field(default='100000', pattern=r'^\d+(\.\d{1,2})?$')

class AuditInput(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=8)
    business_date: date
    allow_demo: bool = False

class ReviewInput(BaseModel):
    status: Literal['compliant','violation','insufficient','not_applicable']
    note: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=100)


@app.get('/api/health')
def health(): return {'status':'ok'}

@app.get('/api/providers')
def providers(): return DEFAULTS

@app.get('/api/agents')
def list_agents(): return [public_agent(a) for a in store.agents()]

@app.post('/api/agents', status_code=201)
def new_agent(body: AgentInput): return public_agent(agents.create_agent(body.name,body.description))

@app.get('/api/agents/{agent_id}')
def get_agent(agent_id: str): return public_agent(require_agent(agent_id))

@app.patch('/api/agents/{agent_id}')
def edit_agent(agent_id: str, body: AgentInput):
    a = require_agent(agent_id); a.update(body.model_dump()); store.save_agent(a); return public_agent(a)

@app.put('/api/agents/{agent_id}/config')
def config(agent_id: str, body: ConfigInput):
    a = require_agent(agent_id)
    data = body.model_dump(exclude={'api_key'})
    validate_config(data)
    if data['url'] != a['config']['url'] or data['provider'] != a['config']['provider']:
        SECRETS.pop(agent_id, None)
    if body.api_key is not None: SECRETS[agent_id] = body.api_key
    a['config'] = data; store.save_agent(a)
    return public_agent(a)

@app.post('/api/agents/{agent_id}/probe')
async def probe(agent_id: str):
    a = require_agent(agent_id)
    try:
        result = await decide(a['config'], '文件必须写明供应商。', '供应商：甲公司。', agent_id)
        return {'ok': True, **result}
    except ModelFailure as e:
        raise HTTPException(502,str(e)) from None

@app.get('/api/agents/{agent_id}/documents')
def documents(agent_id: str):
    require_agent(agent_id); return store.documents(agent_id)

@app.post('/api/agents/{agent_id}/documents', status_code=201)
async def upload(agent_id: str, kind: Literal['standard','review']='review', file: UploadFile=File(...)):
    require_agent(agent_id)
    data = await file.read(MAX_BYTES+1)
    await file.close()
    try:
        doc = await asyncio.to_thread(parse_document, file.filename or 'document', data)
    except DocumentFailure as e: raise HTTPException(422,str(e)) from None
    doc['kind'] = kind
    return store.save_document(agent_id, doc, data)

@app.post('/api/agents/{agent_id}/rules', status_code=201)
def add_rule(agent_id: str, body: RuleInput):
    a = require_agent(agent_id)
    doc = store.get_document(agent_id,body.document_id)
    if not doc or doc.get('kind') != 'standard': raise HTTPException(422,'请选择本 Agent 的制度原文')
    block = next((x for x in doc['blocks'] if x['id']==body.block_id),None)
    if not block or body.source_quote not in block['text']: raise HTTPException(422,'规则引用必须来自所选制度原文')
    if body.effective_to and body.effective_to <= body.effective_from: raise HTTPException(422,'失效日期必须晚于生效日期')
    if any(r['id']==body.id and (r['version']==body.version or r['effective_from']==body.effective_from.isoformat()) for r in a['rules']):
        raise HTTPException(409,'同一规则的版本或生效日期重复')
    rule=body.model_dump(mode='json');rule['source_location']=block['location'];rule['demo']=False
    a['rules'].append(rule);store.save_agent(a);return rule

@app.post('/api/agents/{agent_id}/rules/{rule_id}/confirm')
def confirm(agent_id: str, rule_id: str, version: str):
    a=require_agent(agent_id)
    rule=next((x for x in a['rules'] if x['id']==rule_id and x['version']==version),None)
    if not rule: raise HTTPException(404,'规则不存在')
    rule['confirmed']=True;rule['confirmed_at']=store.now();store.save_agent(a);return rule

@app.get('/api/agents/{agent_id}/audits')
def audits(agent_id: str):
    require_agent(agent_id)
    return [{k:a[k] for k in ('id','agent_id','created_at','status','conclusion','total')} | {'name':'、'.join(d['name'] for d in a['documents'])} for a in store.list_audits(agent_id)]

@app.post('/api/agents/{agent_id}/audits', status_code=202)
async def start_audit(agent_id: str, body: AuditInput):
    a = require_agent(agent_id)
    docs = [store.get_document(agent_id,x) for x in dict.fromkeys(body.document_ids)]
    if any(d is None or d.get('kind')!='review' for d in docs): raise HTTPException(404,'待审核文件不存在或不属于本 Agent')
    if len(full_text(collect(docs))) > 24000: raise HTTPException(422,'合并后的文本超出 24000 字符上限，未执行审核')
    rules=select_rules(a['rules'],body.business_date.isoformat(),body.allow_demo)
    if not rules: raise HTTPException(422,'该业务日期没有已确认的生效规则；演示 Agent 可显式启用演示规则')
    if len(runtime.TASKS)>=10: raise HTTPException(429,'审核队列已满，请稍后重试')
    return runtime.launch(a,docs,rules,body.business_date.isoformat())

@app.get('/api/agents/{agent_id}/audits/{audit_id}')
def audit_detail(agent_id: str, audit_id: str):
    a=store.get_audit(agent_id,audit_id)
    if not a: raise HTTPException(404,'审核记录不存在')
    return a

@app.post('/api/agents/{agent_id}/audits/{audit_id}/review/{rule_id}')
def review(agent_id: str, audit_id: str, rule_id: str, body: ReviewInput):
    a=audit_detail(agent_id,audit_id)
    if a['status'] in ('queued','running'): raise HTTPException(409,'请等待审核结束再复核')
    finding=next((x for x in a['findings'] if x['rule_id']==rule_id),None)
    if not finding: raise HTTPException(404,'逐条结果不存在')
    record={**body.model_dump(),'time':store.now()}
    finding.setdefault('review_history',[]).append(record);finding['review']=record
    a['conclusion']=runtime.conclusion(a['findings'],a['status']=='completed')
    a['events'].append({'time':store.now(),'rule_id':rule_id,'action':'human_review','status':body.status})
    store.save_audit(a);return a

@app.get('/api/agents/{agent_id}/audits/{audit_id}/report')
def report(agent_id: str,audit_id: str):
    a=audit_detail(agent_id,audit_id)
    lines=[f"# {a['agent_name']}审核报告",'',f"结论：{a['conclusion']}",f"状态：{a['status']}",f"业务日期：{a['business_date']}",f"模型：{a['config']['model']}",f"配置版本：{a['config_version']}",f"流程版本：{a['pipeline_version']}",f"审核编号：{a['id']}",f"演示规则：{'是' if a['demo'] else '否'}"]
    for f in a['findings']:
        lines += ['',f"## {f['rule_title']} — {LABELS.get(f['status'],'执行失败')}",f"制度版本：{f['rule_version']}；位置：{f['rule_location']}",f['rule_text'],f['reason']]
        if f.get('score') is not None: lines += [f"模型分数：{f['score']:.4f}（辅助分流，不是准确率）"]
        for e in f['evidence']: lines += [f"- {e['document_name']} · {e['location']}：{e['text']}"]
        for review in f.get('review_history',[]): lines += [f"人工复核：{review['reviewer']}，{LABELS[review['status']]}；{review['note']}"]
    return PlainTextResponse('\n'.join(lines),media_type='text/markdown')

@app.get('/api/samples/{name}')
def sample(name: Literal['employment','purchase']):
    return FileResponse(f'fixtures/{name}.txt', media_type='text/plain; charset=utf-8')

app.mount('/static',StaticFiles(directory='static'),name='static')
@app.get('/')
def index(): return FileResponse('static/index.html')
