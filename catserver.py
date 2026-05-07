#!/usr/bin/env python3
"""
catserver.py — bypasses LM Studio's CORS by serving catsim.html and proxying the API.

WHY: LM Studio's CORS is unreliable, especially for `file://` origins. This script
serves catsim from a real http origin and forwards `/lm/*` to LM Studio with CORS
headers added. catsim & API become same-origin → CORS doesn't apply → it just works.

USAGE:
    Put this file next to catsim.html, then:
        python3 catserver.py
    Open in your browser:
        http://localhost:8765/

REQUIREMENTS: Python 3.7+ (stdlib only).

CONFIG: edit the two constants below if you need different ports.
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import sys
import os
import signal

# ─── CONFIG ─────────────────────────────────────────────────────────────────
LM_STUDIO_HOST = 'http://localhost:1234'
PORT           = 8765
HTML_NAMES     = ['catsim.html', 'pr_sim.html', 'pr-sim.html', 'prsim.html', 'pr sim.html']
# ────────────────────────────────────────────────────────────────────────────


class CatHandler(http.server.SimpleHTTPRequestHandler):

    # ── pretty logging ─────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        method = getattr(self, 'command', '?')
        try:
            status = args[1]
        except IndexError:
            status = '?'
        color = '\033[32m' if str(status).startswith(('2', '3')) else '\033[31m'
        sys.stderr.write(
            f'\033[36m[catsim]\033[0m {method:<6} {self.path:<45} {color}{status}\033[0m\n'
        )

    # ── CORS ───────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, *')
        self.send_header('Access-Control-Max-Age',       '3600')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── routing ────────────────────────────────────────────────────────────
    def do_GET(self):
        # Auto-serve the catsim html at root
        if self.path in ('/', '/index.html'):
            html_file = self._find_html()
            if html_file:
                self.path = '/' + html_file
                return super().do_GET()
            return self._send_help(404)

        if self.path.startswith('/lm/'):
            return self._proxy()

        # Static file serving
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith('/lm/'):
            return self._proxy()
        return self.send_error(405, 'POST is only proxied via /lm/* paths')

    def send_error(self, code, message=None, explain=None):
        # Replace bland 404s with a helpful setup page
        if code == 404:
            return self._send_help(404)
        return super().send_error(code, message, explain)

    # ── proxy core ─────────────────────────────────────────────────────────
    def _proxy(self):
        target = LM_STUDIO_HOST + self.path[3:]   # strip "/lm"

        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(target, data=body, method=self.command)
        for h, v in self.headers.items():
            hl = h.lower()
            if hl in ('host', 'content-length', 'origin', 'referer', 'connection'):
                continue
            # catsim sends text/plain to dodge browser preflight; LM Studio prefers JSON
            if hl == 'content-type' and 'text/plain' in v.lower():
                req.add_header('Content-Type', 'application/json')
            else:
                req.add_header(h, v)

        try:
            upstream = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            try: self.wfile.write(e.read())
            except Exception: pass
            return
        except urllib.error.URLError as e:
            self.send_response(502)
            self._cors()
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(
                f'catsim proxy: cannot reach LM Studio at {LM_STUDIO_HOST}\n'
                f'reason: {e.reason}\n\n'
                f'is LM Studio running with the local server started?'.encode()
            )
            return

        with upstream:
            self.send_response(upstream.status)
            for h, v in upstream.headers.items():
                if h.lower() in ('transfer-encoding', 'connection', 'content-encoding', 'content-length'):
                    continue
                self.send_header(h, v)
            self._cors()
            self.end_headers()
            try:
                while True:
                    chunk = upstream.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass   # client cancelled — fine

    # ── helpers ────────────────────────────────────────────────────────────
    def _find_html(self):
        cwd = os.getcwd()
        try:
            files = os.listdir(cwd)
        except OSError:
            return None
        for name in HTML_NAMES:
            if name in files:
                return name
        lower = {f.lower(): f for f in files if f.lower().endswith('.html')}
        for name in HTML_NAMES:
            if name.lower() in lower:
                return lower[name.lower()]
        for f in sorted(files):
            if f.lower().endswith('.html'):
                return f
        return None

    def _send_help(self, code):
        cwd = os.getcwd()
        try:
            html_files = sorted(f for f in os.listdir(cwd) if f.lower().endswith('.html'))
        except OSError:
            html_files = []

        if html_files:
            files_html = '<ul>' + ''.join(
                f'<li><a href="/{f}">{f}</a></li>' for f in html_files
            ) + '</ul>'
            file_section = f'<p>HTML files I see in this folder:</p>{files_html}'
        else:
            file_section = (
                '<p style="color:#ff6680">'
                '⚠ No HTML files found in this folder.<br>'
                f'Put <code>catsim.html</code> in: <code>{cwd}</code><br>'
                'then refresh this page.</p>'
            )

        body = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>catsim — setup</title>
<style>
  body {{ background:#0d0820; color:#f5e8ff;
         font-family:ui-monospace,Menlo,Consolas,monospace;
         padding:40px; max-width:680px; margin:0 auto; line-height:1.7; }}
  h1 {{ font-family:Georgia,serif; font-style:italic; font-size:36px;
        background:linear-gradient(90deg,#ff4d8d,#ffc857,#7df9ff);
        -webkit-background-clip:text; background-clip:text; color:transparent;
        margin:0 0 6px; letter-spacing:-1px; }}
  .sub {{ color:#9d88c4; font-size:12px; text-transform:uppercase;
         letter-spacing:1.5px; margin-bottom:24px; }}
  code {{ background:#1d1640; padding:2px 6px; border-radius:3px; color:#6dffb4; }}
  a {{ color:#7df9ff; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .box {{ background:#1d1640; border:1px solid #4a2f7a; border-radius:10px;
          padding:16px 20px; margin-top:18px; }}
  ul {{ padding-left:22px; }}
  li {{ margin:4px 0; }}
  .cat {{ font-size:60px; line-height:1; margin-bottom:8px; }}
  .err {{ color:#ff6680; }}
</style></head>
<body>
  <div class="cat">🙀</div>
  <h1>catsim — page not found</h1>
  <div class="sub">but the proxy is running, that's the good news</div>

  <div class="box">{file_section}</div>

  <div class="box">
    <strong>What I expected:</strong>
    <ul>
      <li>A file named <code>catsim.html</code> next to <code>catserver.py</code></li>
      <li>Then <code>http://localhost:{PORT}/</code> serves it automatically</li>
    </ul>
  </div>

  <p style="margin-top:24px; font-size:11px; opacity:0.65;">
    LM Studio proxy is also live at <code>/lm/*</code> →
    <code>{LM_STUDIO_HOST}</code> with CORS headers added.
  </p>
</body></html>'''.encode('utf-8')

        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    here = os.path.dirname(os.path.abspath(__file__)) or '.'
    os.chdir(here)

    found = None
    for name in HTML_NAMES:
        if os.path.exists(os.path.join(here, name)):
            found = name
            break

    try:
        server = ThreadedServer(('localhost', PORT), CatHandler)
    except OSError as e:
        sys.stderr.write(f'\n\033[31m✗ Cannot bind to port {PORT}: {e}\033[0m\n')
        sys.stderr.write(f'  Either another process is using it, or change PORT in this file.\n\n')
        sys.exit(1)

    print(f'''\033[35m
  ╱|、         catsim proxy + server
 (˚ˎ 。7        bypassing LM Studio CORS the easy way
  |、˜〵
  じしˍ,)ノ\033[0m

\033[32m✓ open this in your browser:\033[0m  \033[36mhttp://localhost:{PORT}/\033[0m
\033[32m✓ proxying to LM Studio:\033[0m       {LM_STUDIO_HOST}  →  /lm/*
\033[33m  same-origin = no CORS = it just works\033[0m
''', flush=True)

    if found:
        print(f'\033[32m✓ found:\033[0m {found}\n', flush=True)
    else:
        print(f'\033[33m⚠ no catsim html found in {here}\033[0m')
        print(f'\033[33m  put catsim.html here, then reload http://localhost:{PORT}/\033[0m\n', flush=True)

    print('press \033[36mCtrl+C\033[0m to stop.\n', flush=True)

    def shutdown(_sig, _frm):
        print('\n\033[33m🐾 catsim stopped. meow.\033[0m')
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    server.serve_forever()


if __name__ == '__main__':
    main()
