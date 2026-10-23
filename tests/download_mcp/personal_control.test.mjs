import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';

// Run the real control handlers with only persistence/dispatch replaced in memory.
function fixture(status = 'COMPLETED') {
  let row = {revision: 1, payload: {download_id: 'proof', purpose: 'personal_archive', status,
    drive_verified: true, assets: [], failed_files: [], drive_refs: [{file_id: 'verified-original', private_verified: true, checksum_verified: true}]}};
  const getJob = async () => structuredClone(row);
  const updateJob = async (id, revision, payload) => { row = {revision: revision + 1, payload}; return row; };
  const requireText = value => value;
  const GITHUB_APP_DISPATCHER = {};
  const dispatchAfterDurableQueue = async ({job, persist}) => persist(job);
  const src = readFileSync(new URL('../../supabase/functions/download-mcp/index.ts', import.meta.url), 'utf8');
  const code = src.slice(src.indexOf('function mergeRefs('), src.indexOf('async function callTool('));
  const funcs = eval('(function(){' + stripTypeScriptTypes(code) + '; return {resume,retry,finalize};})()');
  return {...funcs, state: () => structuredClone(row)};
}

test('personal manual archive and verify results cannot inject trusted receipts in any state', async () => {
  for (const status of ['COMPLETED', 'FAILED', 'ARCHIVING', 'QUEUED']) {
    for (const type of ['drive_archive_result', 'drive_verify_result']) {
      const f = fixture(status), before = f.state();
      await assert.rejects(f.resume({download_id: 'proof', result: {type, verified: true,
        drive_refs: [{file_id: 'unverified-shared', private_verified: true, checksum_verified: true}]}}, 'test'), /independent Drive verification/);
      assert.deepEqual(f.state(), before);
    }
  }
});

test('retry invalidates personal verification and finalize cannot reuse old receipts', async () => {
  const f = fixture();
  await f.retry('proof', 'test');
  assert.equal(f.state().payload.drive_verified, false);
  assert.deepEqual(f.state().payload.drive_refs, []);
  await assert.rejects(f.finalize('proof', false, 'test'), /verified/);
});
