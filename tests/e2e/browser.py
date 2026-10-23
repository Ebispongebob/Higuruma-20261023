"""浏览器完整业务路径：使用真实后端和模型，不拦截或模拟请求。"""
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = os.getenv('BROWSER_E2E_URL', 'http://127.0.0.1:8766')
ARTIFACTS = Path('artifacts/browser')


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / 'failure.png').unlink(missing_ok=True)
    agent_name = '供应商资料审核-' + str(time.time_ns())[-6:]
    results = []
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda exc: errors.append(type(exc).__name__))

        def done(name):
            results.append({'case': name, 'passed': True})
            print('通过', name, flush=True)

        def no_overflow():
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), '页面发生横向溢出'

        try:
            page.goto(BASE, wait_until='networkidle')
            expect(page.locator('.agent-nav').filter(has_text='劳动合同审核')).to_have_count(1)
            expect(page.locator('.agent-nav').filter(has_text='采购文件审核')).to_have_count(1)
            expect(page.locator('#agent-title')).to_have_text('劳动合同审核')
            expect(page.locator('#rule-count')).to_have_text('30 条审核规则')
            no_overflow()
            page.screenshot(path=str(ARTIFACTS / 'desktop.png'), full_page=True)
            done('桌面首页与两个独立 Agent')

            page.get_by_role('button', name='模型设置', exact=True).click()
            dialog = page.locator('#config-dialog')
            expect(dialog).to_be_visible()
            expect(dialog.locator('[name=api_key]')).to_have_value('')
            page.get_by_role('button', name='保存并测试连接').click()
            expect(page.locator('#probe-result')).to_contain_text('连接成功', timeout=120000)
            dialog.locator('.close').click()
            done('本地模型连接测试与密钥不回显')

            page.get_by_role('button', name='试试示例文件').click()
            expect(page.locator('#selected-files')).to_contain_text('劳动合同示例.txt')
            page.get_by_role('button', name='开始审核').click()
            expect(page.locator('.report-top')).to_contain_text('审核完成 · 30 / 30 条', timeout=180000)
            expect(page.locator('.finding')).to_have_count(30)
            expect(page.locator('.report-top h2')).to_have_text('发现不符合项')
            expect(page.locator('[data-rule="labor-contract-law-0019"] summary')).to_contain_text('不符合')
            page.screenshot(path=str(ARTIFACTS / 'audit.png'), full_page=True)
            with page.expect_popup() as popup:
                page.get_by_role('link', name='查看 / 导出完整报告').click()
            report = popup.value
            report.wait_for_load_state()
            expect(report.locator('body')).to_contain_text('配置版本')
            expect(report.locator('body')).to_contain_text('第十九条')
            report.close()
            done('法律示例真实审核与完整报告')

            finding = page.locator('[data-rule="labor-contract-law-0019"]')
            if not finding.get_attribute('open') == '':
                finding.locator('summary').click()
            finding.get_by_role('button', name='人工复核').click()
            form = page.locator('#review-form')
            form.locator('[name=status]').select_option('violation')
            form.locator('[name=reviewer]').fill('浏览器验收')
            form.locator('[name=note]').fill('已核对试用期上限与合同日期。')
            form.get_by_role('button', name='保存复核记录').click()
            expect(page.locator('#review-dialog')).not_to_be_visible()
            expect(page.locator('[data-rule="labor-contract-law-0019"]')).to_contain_text('浏览器验收')
            page.get_by_role('button', name='新建审核').click()
            page.locator('#history button').first.click()
            expect(page.locator('[data-rule="labor-contract-law-0019"]')).to_contain_text('已核对试用期上限')
            done('人工复核与历史回看')

            page.get_by_role('button', name='新建 Agent', exact=True).click()
            form = page.locator('#agent-form')
            form.locator('[name=name]').fill(agent_name)
            form.locator('[name=description]').fill('检查供应商资料，独立管理规则和审核记录。')
            form.get_by_role('button', name='创建 Agent', exact=True).click()
            expect(page.locator('#agent-title')).to_have_text(agent_name)
            expect(page.locator('#rule-count')).to_have_text('0 条审核规则')
            expect(page.locator('#history')).to_contain_text('新的审核记录会显示在这里')
            done('新建 Agent 不继承其他规则和历史')

            page.get_by_role('button', name='制度与规则').click()
            page.locator('.add-rule summary').click()
            text = '供应商资料必须填写供应商名称。'
            page.locator('#standard-input').set_input_files({'name': '供应商制度.txt', 'mimeType': 'text/plain', 'buffer': text.encode()})
            source = page.locator('#rule-form [name=source]')
            expect(source.locator('option')).to_have_count(2)
            source.select_option(index=1)
            form = page.locator('#rule-form')
            expect(form.locator('[name=source_quote]')).to_have_value(text)
            form.locator('[name=id]').fill('S1')
            form.locator('[name=version]').fill('v1')
            form.locator('[name=title]').fill('供应商名称')
            form.locator('[name=scope]').fill('供应商资料')
            form.locator('[name=effective_from]').fill('2020-01-01')
            form.get_by_role('button', name='添加规则', exact=True).click()
            expect(page.locator('#rules-summary')).to_have_text('共 1 条规则，其中 0 条已经人工确认。')
            page.get_by_role('button', name='核对并确认').click()
            expect(page.locator('#rules-summary')).to_have_text('共 1 条规则，其中 1 条已经人工确认。')
            page.locator('#rules-dialog .close').click()
            done('上传制度、关联原文、添加及确认规则')

            page.locator('#message').fill('供应商资料\n供应商名称：甲公司。')
            page.get_by_role('button', name='开始审核').click()
            expect(page.locator('.report-top')).to_contain_text('审核完成 · 1 / 1 条', timeout=120000)
            expect(page.locator('.finding')).to_have_count(1)
            expect(page.locator('.finding')).to_contain_text('甲公司')
            page.get_by_role('button', name='采购文件审核', exact=False).click()
            expect(page.locator('#agent-title')).to_have_text('采购文件审核')
            expect(page.locator('#history')).to_contain_text('新的审核记录会显示在这里')
            page.get_by_role('button', name=agent_name, exact=False).click()
            expect(page.locator('#history button')).to_have_count(1)
            done('自建 Agent 粘贴审核与历史隔离')

            page.get_by_role('button', name='模型设置', exact=True).click()
            form = page.locator('#config-form')
            form.locator('[name=provider]').select_option('commandcode')
            expect(form.locator('[name=model]')).to_have_value('typesafe/jev')
            expect(form.locator('[name=url]')).to_have_value('https://api.commandcode.ai/provider/v1/systemone')
            form.get_by_role('button', name='保存设置', exact=True).click()
            expect(page.locator('#model-name')).to_have_text('Jev')
            page.get_by_role('button', name='模型设置', exact=True).click()
            form.locator('[name=provider]').select_option('local')
            form.get_by_role('button', name='保存设置', exact=True).click()
            expect(page.locator('#model-name')).to_have_text('本地 d1-3B')
            done('Jev 配置切换与保存（未调用 Jev）')

            page.locator('#file-input').set_input_files({'name': '损坏.pdf', 'mimeType': 'application/pdf', 'buffer': b'invalid'})
            page.get_by_role('button', name='开始审核').click()
            expect(page.locator('#error')).to_contain_text('损坏')
            expect(page.get_by_role('button', name='开始审核')).to_be_enabled()
            done('上传失败可见且允许再次操作')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.get_by_role('button', name='展开侧栏').click()
            page.get_by_role('button', name='劳动合同审核', exact=False).click()
            expect(page.locator('#sidebar')).not_to_be_visible()
            expect(page.locator('#agent-title')).to_have_text('劳动合同审核')
            no_overflow()
            page.screenshot(path=str(ARTIFACTS / 'mobile.png'), full_page=True)
            page.get_by_role('button', name='制度与规则').click()
            expect(page.locator('#rules-dialog')).to_be_visible()
            expect(page.locator('#rule-list .rule-row')).to_have_count(30)
            expect(page.locator('#rule-form [name=source_quote]')).to_have_value('')
            expect(page.locator('#rule-form [name=title]')).to_have_value('')
            expect(page.locator('#review-form [name=note]')).to_have_value('')
            no_overflow()
            page.screenshot(path=str(ARTIFACTS / 'mobile-rules.png'), full_page=True)
            page.locator('#rules-dialog .close').click()
            done('手机首页、侧栏切换、规则窗口及表单草稿隔离')
            assert not errors, '存在页面脚本异常'
            done('全流程无页面脚本异常')
        except Exception as exc:
            page.screenshot(path=str(ARTIFACTS / 'failure.png'), full_page=True)
            # 错误详情不收集表单值、网络响应或本机路径。
            results.append({'case': '后续浏览器步骤', 'passed': False, 'error': type(exc).__name__})
            print('浏览器检查中断:', type(exc).__name__, flush=True)
        finally:
            browser.close()
    report = {'scope': '真实浏览器、后端与本地 d1；不拦截请求，未调用 Jev',
              'passed': sum(r['passed'] for r in results), 'total': len(results),
              'results': results, 'screenshots': str(ARTIFACTS)}
    Path('reports/browser-e2e.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
