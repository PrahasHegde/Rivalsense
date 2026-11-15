// Docker builds accept public browser configuration only. Never log values.
const url = process.env.VITE_SUPABASE_URL || '';
const key = process.env.VITE_SUPABASE_PUBLISHABLE_KEY || '';
let publicKey = key.startsWith('sb_publishable_');
try {
  if (key.startsWith('eyJ')) publicKey = JSON.parse(Buffer.from(key.split('.')[1], 'base64url')).role === 'anon';
} catch { publicKey = false; }
let validUrl = false;
try { const parsed = new URL(url); validUrl = parsed.protocol === 'https:' && !parsed.username && !parsed.password && parsed.pathname === '/' && !parsed.search && !parsed.hash; } catch {}
if (!validUrl || !publicKey) {
  console.error('Provide VITE_SUPABASE_URL and a public publishable/anon key. Secret and service-role keys are forbidden.');
  process.exit(1);
}
console.log('Public Supabase build configuration validated.');
