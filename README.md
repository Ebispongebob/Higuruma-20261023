# Higuruma 文件审核工作台

创建多个审核 Agent，为每个 Agent 配置制度、规则和决策模型。上传文件后，系统遍历生效规则，保存逐条判定、原文引用和人工复核记录。

## 本地运行

```sh
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-access-log
```

打开 <http://127.0.0.1:8765>。侧栏可创建和切换 Agent。各 Agent 的制度、规则、模型设置和审核记录独立保存。

首次启动提供两个演示 Agent：

- 劳动合同审核：来自 `chinese-law-corpus` 的《劳动合同法》，选用 30 条规则。
- 采购文件审核：审批门槛和必填字段两条演示规则。

演示规则明确标为未经业务人工确认。自建 Agent 从空规则开始；上传制度后，需要引用真实原文添加并确认规则，才能发起审核。业务日期决定适用版本，失效日期为不再适用的第一天。

## 模型配置

页面“模型设置”支持请求地址、模型名称、密钥、超时和复核分流阈值。设置只作用于当前 Agent。密钥不回显，只保存在进程内存，重启后需从环境变量或页面重新提供。

本地服务优先：启动时发现当前用户已运行的 `llama-server`，读取其端口和现有鉴权配置。只调用服务，不修改服务。也可以使用环境变量：

| 变量 | 用途 |
| --- | --- |
| `D1_URL` | 完整决策接口地址，例如 `http://127.0.0.1:8080/v1/systemone` |
| `D1_API_KEY` | 本地模型服务密钥 |
| `COMMAND_CODE_URL` | Jev 完整接口地址，默认 `https://api.commandcode.ai/provider/v1/systemone` |
| `COMMAND_CODE_API_SECRET` | Command Code 密钥 |
| `HIGURUMA_DATA_DIR` | 本地存储目录，默认 `.runtime` |

启动时读取当前目录已有的 `.env`。不要将实际凭据加入版本库。`.env.example` 仅包含空凭据。应用不会把页面提供的密钥写入配置文件、数据库或日志。更换请求地址时，旧地址的密钥不会自动发送到新地址。

本地 d1 和 Jev 均使用 `systemone` 决策协议，不使用聊天补全接口。Jev 接入已实现，本轮按用户要求跳过真实调用。

## 文件和报告

支持 UTF-8 TXT、文本 PDF、DOCX 正文与表格。最大上传 8 MB、PDF 100 页、审核输入 24000 字符。超限时明确拒绝，不截断审核。扫描页、无法解析的文件，以及含未支持附加内容的 DOCX 会报错。可同时上传正文和附件。

程序处理明确的金额、日期、必填字段和试用期上限；其余语义交给决策模型。模型分数只用于分流。全部规则不适用、证据不足或执行失败时，不输出整体符合。报告保留制度版本、原文位置、模型、配置摘要和流程版本。人工复核另存，不覆盖原判定。

本地原始文件、解析结果、Agent 配置和审核记录存放在 SQLite 数据库中。应用仅面向本地单用户工作空间，不包含多人账号系统。

## 端到端验证

不包含单元测试或替身模型。业务测试通过 HTTP 导入制度、确认规则、上传文件、调用本地模型、检查报告及复核结果。

在一个终端启动独立测试存储：

```sh
HIGURUMA_DATA_DIR=.runtime/e2e uv run uvicorn app.main:app --host 127.0.0.1 --port 8766 --no-access-log
```

在另一个终端运行：

```sh
uv run python tests/e2e/run.py
uv run python -m scripts.check_model
```

结果写入 `reports/e2e.json`、`reports/legal-e2e.json` 和 `reports/model-check.json`。第二条命令单独检查模型对 20 组中文输入的原始表现，与完整审核流程的程序校验结果分开统计。

当前样例是程序构造的演示材料，不是独立人工标注。原始模型检查存在错误，不能以业务流程测试通过代替模型效果验收。达到 milestone 中的 30 份文件、100 条独立人工标注和召回率要求，仍需实际材料与人工核对。

## 数据来源

法律语料使用 [chinese-law-corpus](https://github.com/lttxzmj/chinese-law-corpus)，固定提交 `6cdf25cfd7425b20e720b96a54f3840c69b9564f`。原始文件、来源和校验摘要保存在 `fixtures/corpus/`。数据整理部分采用 CC0-1.0。数据集是非官方整理，不能将演示结论视为人工法律审查结果。

接口依据：[Liquid AI d1](https://huggingface.co/LiquidAI/d1-3B-GGUF)、[Command Code Jev](https://commandcode.ai/models/jev)。
