import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const authScripts = JSON.parse(execFileSync(process.env.RUBRA_TEST_PYTHON || '.venv/bin/python', ['-c', "import json; from zenless.provider_auth import authentication_script; from zenless.managed_browser import PROVIDERS; print(json.dumps({k:authentication_script(k,s.inputs) for k,s in PROVIDERS.items()}))"], { cwd: '..', encoding: 'utf8' }));

async function store(page: Page, value: Record<string, unknown>) {
  await page.evaluate(async (patch) => {
    const path = '/src/store/index.ts';
    const { useStore } = await import(path);
    useStore.setState(patch);
  }, value);
}

for (const viewport of [{ width: 1000, height: 650 }, { width: 1420, height: 880 }]) {
  test(`settings stay aligned at ${viewport.width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.getByRole('button', { name: 'SETTINGS', exact: true }).click();
    await expect(page.getByText('Default Approval', { exact: true })).toBeVisible();
    const controls = page.locator('main select, main input, main button[role="switch"]');
    for (const box of await controls.evaluateAll((nodes) => nodes.map((node) => {
      const b = node.getBoundingClientRect(); return { left: b.left, right: b.right, width: b.width };
    }))) {
      expect(box.width).toBeGreaterThan(20);
      expect(box.left).toBeGreaterThan(208);
      expect(box.right).toBeLessThanOrEqual(viewport.width - 12);
    }
    await page.getByRole('button', { name: 'MODELS', exact: true }).click();
    await expect(page.getByText('LOCAL AI', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'LINKS', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Reconnect', exact: true })).toBeVisible();
    expect(errors).toEqual([]);
    await page.screenshot({ path: `test-results/settings-${viewport.width}.png` });
  });
}

test('tooltip remains inside the viewport when navigation is collapsed', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 650 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Collapse navigation' }).click();
  await page.getByRole('button', { name: 'SETTINGS', exact: true }).hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toBeVisible();
  const b = await tooltip.boundingBox();
  expect(b!.x).toBeGreaterThanOrEqual(0);
  expect(b!.x + b!.width).toBeLessThan(1000);
  expect(b!.y + b!.height).toBeLessThan(650);
});

test('Play without an AI task creates a test session and can be stopped', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'TEST', exact: true }).click();
  await store(page, { currentJobId: null, activeTestJobId: null, testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 } });
  await page.getByRole('button', { name: 'PLAY', exact: true }).click();
  await expect(page.getByRole('button', { name: 'STOP', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'STOP', exact: true }).click();
  await expect(page.getByText('STOPPING', { exact: true })).toBeVisible();
});

test('connected Studio provides project identity and editor tree', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'EDITOR', exact: true }).click();
  await expect(page.getByText('Workspace', { exact: true }).first()).toBeVisible();
  await page.evaluate(async () => {
    const path = '/src/store/eventHandler.ts';
    const { handleEvent } = await import(path);
    handleEvent({ type: 'STUDIO_STATE_CHANGED', data: { state: 'ONLINE', projectName: 'My Roblox place' } });
  });
  await expect(page.locator('header')).toContainText('My Roblox place');
});

test('empty Home offers actual actions instead of a dash', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'HOME', exact: true }).click();
  await store(page, { jobs: [] });
  await expect(page.getByText('Ready for your next Roblox project.')).toBeVisible();
  await page.getByRole('button', { name: 'Start building', exact: true }).click();
  await expect(page.getByPlaceholder('Message Rubra')).toBeVisible();
});

test('custom window controls call only the intended native methods', async ({ page }) => {
  await page.addInitScript(() => {
    const calls: string[] = [];
    Object.assign(window, { windowCalls: calls, pywebview: { api: {
      minimize_window: async () => { calls.push('minimize'); },
      toggle_maximize: async () => { calls.push('maximize'); },
      close_window: async () => { calls.push('close'); },
    } } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Minimize window' }).click();
  await page.getByRole('button', { name: 'Maximize or restore window' }).click();
  await page.getByRole('button', { name: 'Close window' }).click();
  expect(await page.evaluate(() => (window as unknown as { windowCalls: string[] }).windowCalls)).toEqual(['minimize', 'maximize', 'close']);
  expect(await page.locator('img[alt="Rubra"]').count()).toBe(1);
});

for (const [provider, script] of Object.entries(authScripts)) {
  test(`${provider} requires an account, not just an input`, async ({ page }) => {
    await page.goto('/');
    const markers: Record<string, string> = {
      chatgpt: '<button data-testid="accounts-profile-button">Account</button>',
      deepseek: '<button class="user-avatar">Account</button>',
      gemini: '<a aria-label="Google Account">Account</a>',
      hunyuan: '<button class="user-avatar">Account</button>',
    };
    await page.setContent('<textarea id="prompt-textarea"></textarea><div contenteditable="true" class="ql-editor">Composer</div>');
    expect(await page.evaluate(script as string)).toMatchObject({ ready: false, composer: true });
    await page.locator('body').evaluate((body, html) => body.insertAdjacentHTML('beforeend', html), markers[provider]);
    expect(await page.evaluate(script as string)).toMatchObject({ ready: true, authenticated: true });
    await page.locator('body').evaluate((body) => body.insertAdjacentHTML('beforeend', '<button>Sign in</button>'));
    expect(await page.evaluate(script as string)).toMatchObject({ ready: false });
  });
}


test('model discovery does not confuse generic quality or account buttons with models', async ({ page }) => {
  const script = execFileSync(process.env.RUBRA_TEST_PYTHON || '.venv/bin/python', ['-c', 'from zenless.provider_auth import model_options_script; print(model_options_script())'], { cwd: '..', encoding: 'utf8' });
  await page.goto('/');
  await page.setContent('<button>High</button><button>Thinking</button><button>Account</button><button role="option">GPT-6</button><button data-model="sol">GPT Sol</button>');
  expect(await page.evaluate(script)).toEqual(['GPT-6', 'sol']);
});


test('chat shows summarized process steps and actionable error notifications', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'CHAT', exact: true }).click();
  await store(page, { currentJobId: 'test-job', activities: [] });
  await page.evaluate(async () => {
    const path = '/src/store/eventHandler.ts';
    const { handleEvent } = await import(path);
    handleEvent({ type: 'CHAT_ACTIVITY', data: { activity: { id: 'step', jobId: 'test-job', phase: 'CONTEXT', status: 'RUNNING', title: 'Inspecting scripts', timestamp: Date.now() } } });
    handleEvent({ type: 'JOB_FAILED', data: { jobId: 'test-job', reason: 'Studio disconnected. Reconnect and retry.' } });
  });
  await expect(page.getByText('Inspecting scripts', { exact: true })).toBeVisible();
  await expect(page.getByText('Studio disconnected. Reconnect and retry.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(page.getByText('Studio disconnected. Reconnect and retry.', { exact: true })).not.toBeVisible();
});

test('reduced-motion preference removes CSS transitions', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const button = page.getByRole('button', { name: 'SETTINGS', exact: true });
  await expect(button).toBeVisible();
  expect(await button.evaluate((node) => getComputedStyle(node).transitionDuration)).toBe('0s');
});

test('modern chat offers review prompts and keeps a growing composer in view', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 650 });
  await page.goto('/');
  await page.getByRole('button', { name: 'CHAT', exact: true }).click();
  await expect(page.getByPlaceholder('Message Rubra')).toBeVisible();
  await store(page, { messages: [], jobs: [], currentJobId: null, streamingMessageId: null, activities: [], studioProjectName: 'Existing place' });
  await expect(page.getByText('What should we work on?')).toBeVisible();
  await page.getByRole('button', { name: 'Find and fix errors', exact: true }).click();
  const composer = page.getByPlaceholder('Message Rubra');
  await expect(composer).toHaveValue(/reproduce its errors/);
  await composer.fill('Review the game\nInspect all scripts\nRun Play\nCheck UI\nRepair failures\nRetest\nReport actual evidence');
  const box = await composer.boundingBox();
  expect(box!.height).toBeGreaterThan(48);
  expect(box!.y + box!.height).toBeLessThan(650);
  await page.screenshot({ path: 'test-results/chat-1000.png' });
});

test('inventory error preserves the connected editor and Play action', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'EDITOR', exact: true }).click();
  await expect(page.getByText('Workspace', { exact: true }).first()).toBeVisible();
  await page.evaluate(async () => {
    const { handleEvent } = await import('/src/store/eventHandler.ts');
    handleEvent({ type: 'STUDIO_STATE_CHANGED', data: { state: 'ONLINE', treeError: 'Tree summary has no objects', projectName: 'Existing place' } });
    handleEvent({ type: 'STUDIO_TREE_UPDATED', data: { tree: [] } });
  });
  await expect(page.getByText(/Play remains available/)).toBeVisible();
  await expect(page.locator('header')).toContainText('Existing place');
  await page.getByRole('button', { name: 'TEST', exact: true }).click();
  await store(page, { currentJobId: null, activeTestJobId: null, testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 } });
  await expect(page.getByRole('button', { name: 'PLAY', exact: true })).toBeEnabled();
});

test('test captures display exact dimensions and stale completion does not stop another run', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'TEST', exact: true }).click();
  await store(page, { currentJobId: null, activeTestJobId: null, testCaptures: [], testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 } });
  await page.getByRole('button', { name: 'PLAY', exact: true }).click();
  await expect(page.getByRole('button', { name: 'STOP', exact: true })).toBeVisible();
  await page.evaluate(async () => {
    const { handleEvent } = await import('/src/store/eventHandler.ts');
    const { useStore } = await import('/src/store/index.ts');
    const jobId = useStore.getState().activeTestJobId!;
    handleEvent({ type: 'TEST_CAPTURE', data: { jobId, capture: { id: 'frame', imageUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nGAAAAAASUVORK5CYII=', width: 1920, height: 1080, timestamp: Date.now() } } });
    handleEvent({ type: 'TEST_FINISHED', data: { jobId: 'old-test', passed: true } });
  });
  await expect(page.getByRole('img', { name: /Studio test frame/ })).toBeVisible();
  await expect(page.getByText('1920 × 1080')).toBeVisible();
  await expect(page.getByRole('button', { name: 'STOP', exact: true })).toBeVisible();
  await page.evaluate(async () => {
    const { handleEvent } = await import('/src/store/eventHandler.ts');
    const { useStore } = await import('/src/store/index.ts');
    handleEvent({ type: 'TEST_FINISHED', data: { jobId: useStore.getState().activeTestJobId!, passed: false, cancelled: true } });
  });
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible();
});
