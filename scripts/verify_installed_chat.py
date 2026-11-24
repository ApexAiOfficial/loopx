#!/usr/bin/env python3
"""Check installed wheel assets through the real Chat HTTP handler outside source."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

CHECK = r"""
import hashlib
from pathlib import Path
import threading
from urllib.request import urlopen
import loopx
from loopx.chat_server import ChatHTTPServer, ChatRequestHandler, default_chat_assets_dir
from loopx.presentation.chat_bundle import validate_bundle

bundle = default_chat_assets_dir()
manifest = validate_bundle(bundle)
assert "site-packages" in str(Path(loopx.__file__).resolve()), loopx.__file__
server = ChatHTTPServer(("127.0.0.1", 0), ChatRequestHandler)
server.assets_dir = bundle
server.verbose = False
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()
try:
    for name, digest in manifest["files"].items():
        with urlopen(f"http://127.0.0.1:{server.server_port}/chat/{name}", timeout=10) as response:
            assert response.status == 200
            assert hashlib.sha256(response.read()).hexdigest() == digest, name
    print("Installed Chat HTTP delivery passed: entry, current assets, previous assets and PWA files")
finally:
    server.shutdown()
    server.server_close()
    worker.join()
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="loopx-installed-chat-") as directory:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        subprocess.run(
            [args.python, "-I", "-c", CHECK], cwd=directory, env=env, check=True
        )
