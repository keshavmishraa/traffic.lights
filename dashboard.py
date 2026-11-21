"""Local HTTP dashboard and optional gRPC demo traffic."""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import threading
import time

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc

from network import DESTINATIONS, HEARTBEAT_INTERVAL, LANES


def start_dashboard(service, port, coordinator, demo):
    directory = Path(__file__).parent
    files = {
        "/": ("text/html", "dashboard.html"),
        "/dashboard.css": ("text/css", "dashboard.css"),
        "/dashboard.js": ("text/javascript", "dashboard.js"),
    }
    assets = {path: (f"{kind}; charset=utf-8", (directory / name).read_bytes())
              for path, (kind, name) in files.items()}

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/state":
                state = service.dashboard_state()
                state.update(coordinator=coordinator, demo=demo)
                content_type, body = "application/json", json.dumps(state).encode()
            elif self.path in assets:
                content_type, body = assets[self.path]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_demo(port, stop):
    with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        stub = rpc.CoordinatorStub(channel)

        def join(car, lane, visit):
            trip_id = f"{car}-{visit}"
            destination = random.choice(DESTINATIONS[lane])
            stub.Join(pb.Arrival(lane=lane, car_id=car, trip_id=trip_id,
                                 destination_lane=destination), timeout=2)
            return pb.VehicleRequest(lane=lane, trip_id=trip_id), car, visit

        queues = {lane: deque() for lane in LANES}
        for index in range(1, 9):
            lane = LANES[(index - 1) % len(LANES)]
            queues[lane].append(join(f"Car {index:02d}", lane, 1))
        active = None
        next_heartbeat = 0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_heartbeat:
                for lane in LANES:
                    stub.Heartbeat(pb.LightRequest(lane=lane), timeout=2)
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if active and now >= finish_at:
                request, car, visit = active
                stub.Finish(request, timeout=2)
                lane = random.choice(LANES)
                queues[lane].append(join(car, lane, visit + 1))
                active = None
            if active is None:
                for queue in queues.values():
                    if queue:
                        permit = stub.RequestPass(queue[0][0], timeout=2)
                        if permit.granted:
                            active = queue.popleft()
                            finish_at = time.monotonic() + permit.crossing_seconds
                            break
            stop.wait(0.08)
