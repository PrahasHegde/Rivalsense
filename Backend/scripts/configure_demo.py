"""Configure an isolated local demo using validated public Supabase settings."""
from pathlib import Path
import argparse
import base64
import json
import os
import re
from dotenv import dotenv_values


def public_key(value):
    if value.startswith('sb_publishable_'):
        return True
    try:
        return json.loads(base64.urlsafe_b64decode(value.split('.')[1] + '==='))['role'] == 'anon'
    except (IndexError, ValueError, KeyError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True, help='Original repository path (read only)')
    parser.add_argument('--local-reads', action='store_true', help='Opt in to bounded single-process provider reads')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.source.resolve() == root.resolve():
        raise SystemExit('Use this helper only in the isolated demo worktree, not the original.')
    target = root / 'frontEnd' / '.env.local'
    if target.exists():
        raise SystemExit('A frontend .env.local already exists; review it privately instead of overwriting it.')
    source = dotenv_values(args.source / 'frontEnd' / '.env.local')
    url = source.get('VITE_SUPABASE_URL') or ''
    key = source.get('VITE_SUPABASE_PUBLISHABLE_KEY') or source.get('VITE_SUPABASE_ANON_KEY') or ''
    if not url.startswith('https://') or not public_key(key):
        raise SystemExit('No validated public configuration found. Enter public values in frontEnd/.env.local privately.')
    backend = dotenv_values(root / 'Backend' / '.env')
    backend_url = os.getenv('SUPABASE_URL') or backend.get('SUPABASE_URL') or ''
    backend_key = os.getenv('SUPABASE_PUBLISHABLE_KEY') or backend.get('SUPABASE_PUBLISHABLE_KEY') or ''
    if backend_url.rstrip('/') != url.rstrip('/') or not backend_key.startswith('sb_publishable_'):
        raise SystemExit('Backend public configuration is missing or the project differs; review privately before demo.')
    target.write_text('VITE_SUPABASE_URL=' + url + '\nVITE_SUPABASE_PUBLISHABLE_KEY=' + key + '\nVITE_API_BASE_URL=\n', encoding='utf-8')
    if args.local_reads:
        path = root / 'Backend' / '.env'
        text = path.read_text(encoding='utf-8')
        text = re.sub(r'(?m)^(RIVALSENSE_READ_BUDGET|RIVALSENSE_RECORDING_ENABLED|RESEARCH_HISTORY_ENABLED)=.*\n?', '', text)
        path.write_text(text.rstrip() + '\nRIVALSENSE_READ_BUDGET=local\nRIVALSENSE_RECORDING_ENABLED=false\nRESEARCH_HISTORY_ENABLED=false\n', encoding='utf-8')
    print('Validated public demo configuration prepared. Credentials withheld; original unchanged.')


if __name__ == '__main__':
    main()
