"""Local UI fault fixture: delayed East lists and one lost bulk response after commit.

No fault controls are added to the application. Start the normal app first, then:
  .venv/Scripts/python -m tests.ui_proxy
Open http://127.0.0.1:8766 in Chrome. Bulk request keys are recorded for comparison.
"""
import argparse
import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--target", default="http://127.0.0.1:8765")
    parser.add_argument("--trace", type=Path, default=ROOT / "artifacts" / "ui-network.jsonl")
    parser.add_argument("--east-delay", type=float, default=8)
    parser.add_argument("--drop-first", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--block-storage", choices=["none","write"], default="none")
    args = parser.parse_args()
    lock = threading.Lock()
    state = {"dropped":False}
    trace = args.trace
    trace.parent.mkdir(exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def forward(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            path = urlsplit(self.path).path
            if path == "/api/bulk-issue":
                with lock, trace.open("a",encoding="utf-8") as file:
                    file.write(json.dumps({"event":"received","timestamp":datetime.now(UTC).isoformat(),
                        "actor":self.headers.get("X-Actor-Token"),"key":self.headers.get("Idempotency-Key"),
                        "request":json.loads(body)})+"\n")
            headers = {name:value for name,value in self.headers.items()
                       if name.lower() not in {"host","connection","accept-encoding","content-length"}}
            with httpx.Client(timeout=95,trust_env=False) as client:
                result = client.request(self.command,args.target+self.path,content=body,headers=headers)
            if path == "/api/certificates" and self.headers.get("X-Actor-Token") == "alice-east":
                time.sleep(args.east_delay)
            if path == "/api/bulk-issue":
                with lock:
                    drop = args.drop_first and not state["dropped"] and result.status_code == 200
                    state["dropped"] = state["dropped"] or drop
                    with trace.open("a",encoding="utf-8") as file:
                        file.write(json.dumps({"event":"completed","timestamp":datetime.now(UTC).isoformat(),"actor":self.headers.get("X-Actor-Token"),
                            "key":self.headers.get("Idempotency-Key"),"request":json.loads(body),"http_status":result.status_code,
                            "response_dropped":drop,"result":result.json()})+"\n")
                if drop:
                    self.close_connection = True
                    return
            content = result.content
            if path == "/" and args.block_storage == "write":
                script = b'''<script>const originalSet=Storage.prototype.setItem;
Storage.prototype.setItem=function(k,v){if(k.startsWith('certificate-console:pending:'))throw new DOMException('Test storage denial','SecurityError');return originalSet.call(this,k,v);};</script>'''
                content = content.replace(b"<head>",b"<head>"+script)
            self.send_response(result.status_code)
            for name,value in result.headers.items():
                if name.lower() not in {"transfer-encoding","connection","content-length","content-encoding"}:
                    self.send_header(name,value)
            self.send_header("Content-Length",str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                pass

        do_GET = forward
        do_POST = forward

        def log_message(self, *_):
            pass

    print(f"UI fault fixture: http://127.0.0.1:{args.port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()
