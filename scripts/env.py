"""Initialize separate local env files; migrate the former root .env without printing values."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
backend, frontend, legacy = root / 'backend/.env', root / 'frontend/.env', root / '.env'
if legacy.exists() and not backend.exists():
    source = legacy.read_text().splitlines(keepends=True)
    front_lines, back_lines = [], []
    for line in source:
        key = line.partition('=')[0].strip()
        if key == 'DEV_IDENTITY_ENABLED':
            continue
        (front_lines if key == 'FRONTEND_PORT' or key.startswith('VITE_') else back_lines).append(line)
    backend.write_text(''.join(back_lines))
    backend.chmod(0o600)
    if not frontend.exists():
        frontend.write_text(''.join(front_lines) if front_lines else (root / 'frontend/.env.example').read_text())
        frontend.chmod(0o600)
    legacy.unlink()
    print('Moved local settings into backend/.env and frontend/.env; credentials preserved.')
for path in (backend, frontend):
    if not path.exists():
        path.write_text(path.with_name('.env.example').read_text())
        path.chmod(0o600)
