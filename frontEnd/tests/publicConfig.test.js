import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
const validate = (key, url = 'https://example.supabase.co') => spawnSync(process.execPath, ['scripts/validate-public-config.mjs'], { env: { ...process.env, VITE_SUPABASE_URL: url, VITE_SUPABASE_PUBLISHABLE_KEY: key }, encoding: 'utf8' });
test('browser build accepts public keys only and never logs values', () => {
  for (const key of ['sb_publishable_test', 'eyJ.' + Buffer.from(JSON.stringify({role:'anon'})).toString('base64url') + '.test']) assert.equal(validate(key).status, 0);
  for (const key of ['sb_secret_forbidden', 'eyJ.' + Buffer.from(JSON.stringify({role:'service_role'})).toString('base64url') + '.test', '']) {
    const result = validate(key);
    assert.equal(result.status, 1);
    if (key) assert.ok(!(result.stdout + result.stderr).includes(key));
  }
  assert.equal(validate('sb_publishable_test', 'http://example.supabase.co').status, 1);
});
