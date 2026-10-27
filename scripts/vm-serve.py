#!/usr/bin/env python3
"""Serve the ISO's share-mounting script on a temporary loopback port."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import shlex
import sys

repo = shlex.quote(sys.argv[1])
script = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p {repo}
mount -t 9p -o trans=virtio,version=9p2000.L dotfiles {repo}
printf '\\nCheckout mounted at %s\\n' {repo}
printf 'Run:\\n  cd %s\\n  ./generate-config.py vm --configure\\n  ./bootstrap.sh\\n' {repo}
printf 'Choose /dev/vda and 64 GiB when generating.\\n'
""".encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/startup.sh':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(script)))
        self.end_headers()
        self.wfile.write(script)

    def log_message(self, *args):
        pass


server = HTTPServer(('127.0.0.1', 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
