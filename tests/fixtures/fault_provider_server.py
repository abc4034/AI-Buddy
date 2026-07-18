from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FaultProviderHandler(BaseHTTPRequestHandler):
    mode = "success"
    consumed = False

    def do_POST(self):
        mode = self.mode
        if not self.consumed and mode != "success":
            self.__class__.consumed = True
        else:
            mode = "success"
        if mode == "timeout":
            time.sleep(2)
        if mode == "http_500":
            self.send_response(500)
            self.end_headers()
            return
        if mode == "malformed":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{")
            return
        if mode == "partial_tts_failure" and self.path.endswith("generation"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"output": {"audio": {}}}).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"text": "fault recovery transcript"}).encode("utf-8"))

    def log_message(self, *_args):
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode", choices=("timeout", "http_500", "malformed", "partial_tts_failure", "success"), required=True)
    args = parser.parse_args()
    FaultProviderHandler.mode = args.mode
    FaultProviderHandler.consumed = False
    server = ThreadingHTTPServer(("127.0.0.1", args.port), FaultProviderHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
