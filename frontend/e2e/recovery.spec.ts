import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const authScripts = JSON.parse(execFileSync(process.env.RUBRA_TEST_PYTHON || '.venv/bin/python', ['-c', 'import json; from zenless.provider_auth import authentication_script; from zenless.managed_browser import PROVIDERS; print(json.dumps({k:authentication_script(k,s.inputs) for k,s in PROVIDERS.items()}))'], { cwd: '..', encoding: 'utf8' }));

test('options align and inherit saved approval settings', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 650 });
  await page.goto('/');
  await page.getByRole('button', { name: 'CHAT', exact: true }).click();
  await page.evaluate(async () => {
    const path = '/src/store/index.ts';
    const { useStore } = await import(path);
    const state = useStore.getState();
    useStore.setState({ settings: { ...state.settings, approvalMode: 'FULL_AUTO', maxRevisions: 7 } });
  });
  await page.getByRole('button', { name: 'Task options' }).click();
  await expect(page.getByText('Visual First', { exact: true })).toHaveCount(1);
  await expect(page.locator('select').first()).toHaveValue('FULL_AUTO');
  await expect(page.locator('input[type=number]').first()).toHaveValue('7');
  const rects = await page.locator('select').evaluateAll((nodes) => nodes.map((node) => {
    const r = node.getBoundingClientRect(); return { x: r.x, right: r.right, width: r.width };
  }));
  expect(rects.length).toBeGreaterThan(2);
  for (const rect of rects) {
    expect(Math.abs(rect.x - rects[0].x)).toBeLessThan(1);
    expect(rect.right).toBeLessThanOrEqual(1000);
    expect(rect.width).toBeGreaterThan(110);
  }
  const controls = await page.locator('.rubra-composer button').evaluateAll((nodes) => nodes.map((node) => {
    const r = node.getBoundingClientRect(); return r.y + r.height / 2;
  }));
  expect(Math.max(...controls) - Math.min(...controls)).toBeLessThan(1);
  await page.screenshot({ path: 'test-results/rubra-chat-options.png' });
});

test('account detection works with hidden composer and display contents', async ({ page }) => {
  await page.goto('/');
  await page.setContent('<button aria-label="Open profile menu" style="display:contents"><span>Account</span></button>');
  expect(await page.evaluate(authScripts.chatgpt)).toMatchObject({ authenticated: true, ready: false, composer: false });
  await page.setContent('<div class="ds-avatar"><img src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2220%22 height=%2220%22/%3E" width="20" height="20"></div>');
  expect(await page.evaluate(authScripts.deepseek)).toMatchObject({ authenticated: true, composer: false });
});

test('embedded sender waits for a reactive send button', async ({ page }) => {
  const scripts = JSON.parse(execFileSync(process.env.RUBRA_TEST_PYTHON || '.venv/bin/python', ['-c', 'import json; from zenless.webview_host import WebViewHost; from zenless.managed_browser import PROVIDERS; s=PROVIDERS["chatgpt"]; print(json.dumps([WebViewHost._send_script(s,"test prompt"),WebViewHost._submit_script(s)]))'], { cwd: '..', encoding: 'utf8' }));
  await page.goto('/');
  await page.setContent('<textarea id="prompt-textarea"></textarea><button data-testid="send-button" disabled>Send</button><output>0</output><script>document.querySelector("textarea").oninput=()=>setTimeout(()=>document.querySelector("button").disabled=false,150);document.querySelector("button").onclick=()=>document.querySelector("output").textContent="1";</script>');
  expect(await page.evaluate(scripts[0])).toMatchObject({ ok: true });
  expect(await page.evaluate(scripts[1])).toBe(false);
  await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  expect(await page.evaluate(scripts[1])).toBe(true);
  await expect(page.locator('output')).toHaveText('1');
});

test('test console uses Rubra branding', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'TEST', exact: true }).click();
  await expect(page.getByRole('button', { name: 'RUBRA', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'ZEN', exact: true })).toHaveCount(0);
});
