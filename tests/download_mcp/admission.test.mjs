import test from 'node:test';
import assert from 'node:assert/strict';
import {buildInitialJob, applySourceResolution, buildToolDefinitions, applyExecutorResult} from '../../supabase/functions/download-mcp/core.ts';

const now = '2026-10-23T04:00:00.000Z';
const source = {
  source_url: 'https://publisher.example/journal/article.pdf', filename: 'article.pdf',
  official: true, redistributable: false, publicly_accessible: true,
  access_restriction: 'none', rights_evidence_url: 'https://publisher.example/article',
  license_class: 'Official public download for personal reading; redistribution not established',
};
const job = (purpose) => buildInitialJob({request: 'Generic research publication', constraints: purpose ? {purpose} : {}}, now, 'download-policy');

test('new downloads default to personal archive, not public redistribution', () => {
  assert.equal(job().purpose, 'personal_archive');
  assert.throws(() => job('typo'), /purpose/);
});
test('official public personal downloads accept false redistribution without claiming a license', () => {
  const result = applySourceResolution(job(), {sources: [source]}, now);
  assert.equal(result.status, 'QUEUED');
  assert.equal(result.assets[0].redistributable, false);
  assert.equal(result.assets[0].rights_evidence_url, source.rights_evidence_url);
  assert.equal(result.purpose, 'personal_archive');
});
test('the same source is rejected for public redistribution and for legacy ambiguous purpose', () => {
  assert.throws(() => applySourceResolution(job('public_redistribution'), {sources: [source]}, now), /redistributable/);
  const legacy = job(); delete legacy.purpose;
  assert.throws(() => applySourceResolution(legacy, {sources: [source]}, now), /redistributable/);
});
test('public redistribution still accepts affirmative permission and does not publish anything', () => {
  const result = applySourceResolution(job('public_redistribution'), {sources: [{...source, redistributable: true}]}, now);
  assert.equal(result.status, 'QUEUED');
  assert.equal(result.purpose, 'public_redistribution');
});
test('personal archival never treats login paywall or an unknown restriction as public access', () => {
  for (const access_restriction of ['login', 'paywall', 'drm', 'personal_copy_prohibited', 'unknown']) {
    assert.throws(() => applySourceResolution(job(), {sources: [{...source, access_restriction}]}, now), /access restriction/);
  }
  for (const patch of [{publicly_accessible: false}, {rights_evidence_url: ''}, {license_class: ''}, {redistributable: 'true'}, {official: false}]) {
    assert.throws(() => applySourceResolution(job(), {sources: [{...source, ...patch}]}, now));
  }
});
test('direct URL cannot bypass the public redistribution resolution gate', () => {
  const direct = {request: 'https://publisher.example/doc.pdf'};
  assert.equal(buildInitialJob(direct, now, 'direct-personal').status, 'QUEUED');
  const publicJob = buildInitialJob({...direct, constraints: {purpose: 'public_redistribution'}}, now, 'direct-public');
  assert.equal(publicJob.status, 'RESOLVING');
  assert.equal(publicJob.assets.length, 0);
});
test('personal resolution stays idempotent and applies across document and archive formats', () => {
  for (const filename of ['other.pdf', 'dataset.zip', 'model.gguf', 'release.tar.xz']) {
    const args = {sources: [{...source, source_url: `https://another.example/${filename}`, filename}]};
    const result = applySourceResolution(job(), args, now);
    assert.equal(result.assets[0].filename, filename);
    assert.deepEqual(applySourceResolution(result, args, now), result);
  }
});
test('tool catalog permits truthful false redistribution and exposes purpose and access evidence', () => {
  const tools = buildToolDefinitions();
  const fields = tools.find(t => t.name === 'resolve_download_sources').inputSchema.properties.sources.items.properties;
  assert.equal(fields.redistributable.const, undefined);
  assert.equal(fields.redistributable.type, 'boolean');
  assert.ok(fields.publicly_accessible && fields.access_restriction && fields.rights_evidence_url);
  const constraints = tools[0].inputSchema.properties.constraints;
  assert.deepEqual(constraints.properties.purpose.enum, ['personal_archive', 'public_redistribution']);
});
test('a personal job cannot complete from checksum-only receipts without private Drive verification', () => {
  const initial = buildInitialJob({request: source.source_url}, now, 'private-result');
  const ref = {file_id: 'f1', name: 'article.pdf', size: 12, sha256: 'a'.repeat(64), checksum_verified: true};
  const result = {assets: [{asset_id: 'asset-1', filename: 'article.pdf', status: 'PASS', bytes: 12, sha256: ref.sha256, drive_ref: ref}], drive_refs: [ref], drive_verified: true};
  assert.notEqual(applyExecutorResult(initial, result, now).status, 'COMPLETED');
  const privateRef = {...ref, private_verified: true};
  result.assets[0].drive_ref = privateRef; result.drive_refs = [privateRef];
  assert.equal(applyExecutorResult(initial, result, now).status, 'COMPLETED');
});
