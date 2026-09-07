import test from 'node:test';
import assert from 'node:assert/strict';
import { verifyDriveMetadata } from '../../supabase/functions/download-drive/verification.ts';

const sha = 'a'.repeat(64);
const ref = {file_id: 'f1', name: 'sample.pdf', size: 123, sha256: sha};
const metadata = {id: 'f1', name: 'sample.pdf', size: '123', sha256Checksum: sha, parents: ['leaf'], trashed: false};

test('Drive provider SHA256 is independently compared and retained', () => {
  const verified = verifyDriveMetadata(ref, metadata, 'leaf');
  assert.equal(verified.sha256, sha);
  assert.equal(verified.checksum_verified, true);
  assert.equal(verified.checksum_method, 'google_drive_sha256');
  assert.equal(verified.drive_sha256, sha);
});

test('same size but different cloud bytes fail verification', () => {
  assert.throws(() => verifyDriveMetadata(ref, {...metadata, sha256Checksum: 'b'.repeat(64)}, 'leaf'), /SHA256 mismatch/);
});

test('absent cloud checksum cannot inherit the submitted hash', () => {
  assert.throws(() => verifyDriveMetadata(ref, {...metadata, sha256Checksum: undefined}, 'leaf'), /checksum unavailable/);
});

test('invalid id, name, size, parent and trashed file fail closed', () => {
  for (const change of [{id: 'other'}, {name: 'other.pdf'}, {size: '122'}, {parents: ['other']}, {trashed: true}]) {
    assert.throws(() => verifyDriveMetadata(ref, {...metadata, ...change}, 'leaf'));
  }
  for (const change of [{file_id: ''}, {size: 0}, {size: -1}, {sha256: 'not-a-hash'}]) {
    assert.throws(() => verifyDriveMetadata({...ref, ...change}, metadata, 'leaf'));
  }
});
