import { describe, it, expect } from 'vitest';
import { MockZenlessAPI } from '@/services/mock/mockApi';

describe('MockZenlessAPI', () => {
  it('bootstrap returns boot steps', async () => {
    const api = new MockZenlessAPI();
    const result = await api.bootstrap();
    expect(result.steps).toHaveLength(5);
    expect(result.steps[0].stage).toBe('CORE');
  });

  it('getConnections returns all connection statuses', async () => {
    const api = new MockZenlessAPI();
    const conns = await api.getConnections();
    expect(conns.bridge).toBeDefined();
    expect(conns.chatgpt).toBeDefined();
    expect(conns.deepseek).toBeDefined();
    expect(conns.hunyuan).toBeDefined();
    expect(conns.studio).toBeDefined();
  });

  it('getAgents returns 4 agents', async () => {
    const api = new MockZenlessAPI();
    const agents = await api.getAgents();
    expect(agents).toHaveLength(4);
    expect(agents.map((a) => a.id)).toContain('chatgpt');
    expect(agents.map((a) => a.id)).toContain('deepseek');
    expect(agents.map((a) => a.id)).toContain('hunyuan');
    expect(agents.map((a) => a.id)).toContain('studio');
  });

  it('getJobs returns jobs with valid statuses', async () => {
    const api = new MockZenlessAPI();
    const jobs = await api.getJobs();
    expect(jobs.length).toBeGreaterThan(0);
    for (const job of jobs) {
      expect(['NEW', 'RUNNING', 'PAUSED', 'BLOCKED', 'FAILED', 'COMPLETE']).toContain(job.status);
    }
  });

  it('createJob creates a running job', async () => {
    const api = new MockZenlessAPI();
    const job = await api.createJob('Test task');
    expect(job.title).toBe('Test task');
    expect(job.status).toBe('RUNNING');
    expect(job.id).toMatch(/^job_/);
  });

  it('pauseJob pauses a job', async () => {
    const api = new MockZenlessAPI();
    const job = await api.createJob('Pause test');
    const paused = await api.pauseJob(job.id);
    expect(paused.status).toBe('PAUSED');
  });

  it('cancelJob removes a job', async () => {
    const api = new MockZenlessAPI();
    const job = await api.createJob('Cancel test');
    await api.cancelJob(job.id);
    const jobs = await api.getJobs();
    expect(jobs.find((j) => j.id === job.id)).toBeUndefined();
  });


  it('sendMessage keeps attachment metadata in mock flow', async () => {
    const api = new MockZenlessAPI();
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    const result = await api.sendMessage('With file', undefined, [file]);
    expect(result.messageId).toMatch(/^msg_/);
  });

  it('getReview returns structured reviewer decision and risk', async () => {
    const api = new MockZenlessAPI();
    const review = await api.getReview('job_004');
    expect(['APPROVE', 'REVISE', 'BLOCK']).toContain(review.decision);
    expect(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']).toContain(review.risk);
    expect(Array.isArray(review.warnings)).toBe(true);
  });

  it('getModels exposes provider catalogs and setModel persists selection', async () => {
    const api = new MockZenlessAPI();
    const catalog = await api.getModels();
    expect(catalog.chatgpt.models.length).toBeGreaterThan(0);
    const target = catalog.chatgpt.models[0].id;
    await api.setModel('chatgpt', target);
    expect((await api.getSettings()).models.chatgpt.model).toBe(target);
  });

  it('loginProvider marks the provider session ready', async () => {
    const api = new MockZenlessAPI();
    const result = await api.loginProvider('hunyuan');
    expect(result.ok).toBe(true);
    expect((await api.getConnections()).hunyuan).toBe('READY');
    expect((await api.getAgents()).find((agent) => agent.id === 'hunyuan')?.status).toBe('READY');
  });

  it('Studio lock/use actions mutate mock tree state', async () => {
    const api = new MockZenlessAPI();
    const results = await api.searchStudio('Bomb');
    expect(results.length).toBeGreaterThan(0);
    const id = results[0].id;
    await api.lockStudioReference(id);
    await api.useStudioAsContext(id);
    const node = await api.inspectStudio(id);
    expect(node.locked).toBe(true);
    expect(node.usedAsContext).toBe(true);
  });
  it('sendMessage returns message ID', async () => {
    const api = new MockZenlessAPI();
    const result = await api.sendMessage('Hello');
    expect(result.messageId).toMatch(/^msg_/);
  });

  it('getContext returns context items', async () => {
    const api = new MockZenlessAPI();
    const ctx = await api.getContext('job_004');
    expect(ctx.length).toBeGreaterThan(0);
    expect(ctx[0].name).toBeDefined();
    expect(ctx[0].relevance).toBeGreaterThan(0);
  });

  it('includeContext changes state to included', async () => {
    const api = new MockZenlessAPI();
    const ctx = await api.getContext('job_004');
    const excluded = ctx.find((c) => c.state === 'excluded');
    if (excluded) {
      await api.includeContext(excluded.id);
      const updated = await api.getContext('job_004');
      const item = updated.find((c) => c.id === excluded.id);
      expect(item?.state).toBe('included');
    }
  });

  it('getChanges returns changed files with diffs', async () => {
    const api = new MockZenlessAPI();
    const changes = await api.getChanges('job_004');
    expect(changes.length).toBeGreaterThan(0);
    expect(changes[0].diff).toBeDefined();
    expect(changes[0].status).toMatch(/^[MAD]$/);
  });

  it('getVisual returns 6 views', async () => {
    const api = new MockZenlessAPI();
    const visual = await api.getVisual('job_004');
    expect(visual.views).toHaveLength(6);
    expect(visual.views.map((v) => v.name)).toContain('FRONT');
    expect(visual.views.map((v) => v.name)).toContain('BOTTOM');
  });

  it('getModel returns model info', async () => {
    const api = new MockZenlessAPI();
    const model = await api.getModel('job_004');
    expect(model.state).toBeDefined();
    expect(model.geometryStatus).toBeDefined();
    expect(model.textureStatus).toBeDefined();
  });

  it('getAssets returns assets', async () => {
    const api = new MockZenlessAPI();
    const assets = await api.getAssets();
    expect(assets.length).toBeGreaterThan(0);
    expect(['IMG', 'VIEW', 'GLB', 'TEX', 'RBX']).toContain(assets[0].type);
  });

  it('getStudioTree returns tree with nodes', async () => {
    const api = new MockZenlessAPI();
    const tree = await api.getStudioTree();
    expect(tree.length).toBeGreaterThan(0);
    expect(tree[0].name).toBeDefined();
    expect(tree[0].children).toBeDefined();
  });

  it('searchStudio filters by name', async () => {
    const api = new MockZenlessAPI();
    const results = await api.searchStudio('Bomb');
    expect(results.length).toBeGreaterThan(0);
    expect(results[0].name).toContain('Bomb');
  });

  it('getSettings returns settings with models', async () => {
    const api = new MockZenlessAPI();
    const settings = await api.getSettings();
    expect(settings.models.chatgpt).toBeDefined();
    expect(settings.models.deepseek).toBeDefined();
    expect(settings.models.hunyuan).toBeDefined();
    expect(settings.models.smartRouting).toBeDefined();
  });

  it('getDiagnostics returns diagnostics', async () => {
    const api = new MockZenlessAPI();
    const diags = await api.getDiagnostics();
    expect(diags.length).toBeGreaterThan(0);
    expect(diags[0].severity).toBeDefined();
  });

  it('approveChanges returns ok', async () => {
    const api = new MockZenlessAPI();
    const result = await api.approveChanges('job_004');
    expect(result.ok).toBe(true);
  });

  it('startTest returns ok', async () => {
    const api = new MockZenlessAPI();
    const result = await api.startTest('job_004');
    expect(result.ok).toBe(true);
    const state = await api.getTestState('job_004');
    expect(state.status).toBe('RUNNING');
  });

  it('stopTest returns ok', async () => {
    const api = new MockZenlessAPI();
    await api.startTest('job_004');
    const result = await api.stopTest('job_004');
    expect(result.ok).toBe(true);
    const state = await api.getTestState('job_004');
    expect(state.status).toBe('STOPPED');
  });
});
