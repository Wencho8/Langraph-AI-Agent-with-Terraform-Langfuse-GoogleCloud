"""Small local CLI. Passwords are prompted, never supplied as Make/shell arguments."""
import getpass
import http.cookiejar
import json
import os
from pathlib import Path
import shlex
import sys
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[1]
settings = {}
for line in (root / 'backend/.env').read_text().splitlines():
    name, sep, value = line.partition('=')
    if sep and name.strip() in {'API_PORT', 'APP_ORIGIN', 'AUTH_MODE'}:
        parts = shlex.split(value, comments=True)
        settings[name.strip()] = parts[0] if parts else ''
settings.update({name: os.environ[name] for name in ('API_PORT', 'APP_ORIGIN', 'AUTH_MODE') if name in os.environ})
base = 'http://localhost:' + settings.get('API_PORT', '8088')
origin = settings.get('APP_ORIGIN', 'http://localhost:5173')
jar_path = root / '.local' / 'cookies.txt'
jar = http.cookiejar.MozillaCookieJar(str(jar_path))
if jar_path.exists() and settings.get('AUTH_MODE', 'session') == 'session':
    jar.load(ignore_discard=True)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(path, body=None, csrf=None):
    headers = {'Origin': origin}
    if settings.get('AUTH_MODE') == 'development':
        headers['X-Dev-User-Id'] = os.environ.get('CHAT_USER', 'alice')
    if csrf:
        headers['X-CSRF-Token'] = csrf
    if body is not None:
        headers['Content-Type'] = 'application/json'
    return opener.open(urllib.request.Request(base + '/v1' + path,
        data=json.dumps(body).encode() if body is not None else None, headers=headers), timeout=40)


try:
    command = sys.argv[1]
    if command == 'login':
        with request('/auth/login', {'username': input('Username: '), 'password': getpass.getpass('Password: ')}) as response:
            response.read()
        jar_path.parent.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(jar_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        jar_path.chmod(0o600)
        jar.save(ignore_discard=True)
        print('Signed in. Cookie saved locally; use make history or make chat.')
    elif command == 'history':
        with request('/chat/messages') as response:
            print(json.dumps(json.load(response), indent=2, ensure_ascii=False))
    else:
        csrf = None
        if settings.get('AUTH_MODE', 'session') == 'session':
            with request('/auth/session') as response:
                csrf = json.load(response)['csrf_token']
        if command == 'logout':
            with request('/auth/logout', {}, csrf) as response:
                response.read()
            jar_path.unlink(missing_ok=True)
            print('Signed out.')
        elif command == 'chat':
            with request('/chat/messages', {'message': os.environ.get('CHAT_MESSAGE', 'Hello')}, csrf) as response:
                for line in response:
                    print(line.decode(), end='', flush=True)
except urllib.error.HTTPError as error:
    body = json.loads(error.read())
    print(f"HTTP {error.code}: {body.get('message', body.get('code', 'Request failed'))}", file=sys.stderr)
    sys.exit(1)
except (urllib.error.URLError, TimeoutError):
    print('Cannot reach the backend. Run make start.', file=sys.stderr)
    sys.exit(1)
