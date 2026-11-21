#!/usr/bin/env python3
"""Authoritative, thread-safe junction coordinator (one gRPC server).

Rules:
  - One green lane at a time, and at most one car crossing at a time.
  - Change away from a green lane when another lane waits AND either the
    green lane has no remaining queued cars or >= max_passes cars completed.
  - Do not give another lane green until at least crossing_time (t) seconds
    have elapsed after the LAST car finished crossing.
  - FCFS within each lane; round-robin between lanes.

Fails closed: if a granted vehicle disappears before Finish, the junction
blocks rather than falsely assuming the vehicle has cleared the road.
"""

import argparse
from collections import deque
from concurrent import futures
from dataclasses import dataclass
import logging
import threading
import time

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc

from network import HEARTBEAT_TIMEOUT, LANES, endpoint, host_ip, lane_addresses, require_remote
LOG = logging.getLogger("coordinator")


@dataclass
class Trip:
    lane: str
    car_id: str
    state: str = "WAITING"  # WAITING -> CROSSING -> DONE
    entered_at: float = 0.0


class CoordinatorService:
    def __init__(self, crossing_time: float, max_passes: int, light_ips: dict[str, str]):
        if crossing_time <= 0:
            raise ValueError("crossing_time must be > 0")
        if max_passes < 1:
            raise ValueError("max_passes must be >= 1")
        self.light_ips = light_ips
        self.last_heartbeat: dict[str, float] = {}
        self.t = crossing_time
        self.max_passes = max_passes
        self.lock = threading.RLock()
        self.queues = {lane: deque() for lane in LANES}
        self.trips: dict[str, Trip] = {}
        self.green_lane: str | None = None
        self.last_green_lane: str | None = None
        self.active_trip: str | None = None
        self.last_exit_at: float | None = None
        self.passed_this_green = 0
        self.total_crossed = 0

    def _require_light(self, lane, context):
        if lane not in LANES:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "lane must be A, B, or C")
        transport, _, peer = context.peer().partition(":")
        if transport != "ipv4" or peer.rpartition(":")[0] != self.light_ips[lane]:
            context.abort(grpc.StatusCode.PERMISSION_DENIED,
                          f"Lane {lane} must connect from {self.light_ips[lane]}")

    def Heartbeat(self, request, context):
        self._require_light(request.lane, context)
        with self.lock:
            now = time.monotonic()
            self.last_heartbeat[request.lane] = now
            self._advance(now)
        return pb.Empty()

    def _lights_ready(self, now):
        return all(now - self.last_heartbeat.get(lane, float("-inf")) < HEARTBEAT_TIMEOUT
                   for lane in LANES)

    def _cooldown(self, now):
        return max(0.0, self.last_exit_at + self.t - now) if self.last_exit_at is not None else 0.0

    def _advance(self, now):
        # We never change a light while a vehicle is still in the junction.
        if self.active_trip is not None:
            return

        if not self._lights_ready(now):
            self.green_lane = None
            self.passed_this_green = 0
            return

        if self.green_lane is not None:
            current = self.green_lane
            others_waiting = any(self.queues[lane] for lane in LANES if lane != current)
            green_queue_empty = not self.queues[current]
            quota_reached = self.passed_this_green >= self.max_passes
            if not (others_waiting and (green_queue_empty or quota_reached)):
                return
            self.green_lane = None  # ALL RED before selecting the next green.
            self.last_green_lane = current
            LOG.info("%s GREEN -> RED (others waiting; %d passed this turn)",
                     current, self.passed_this_green)
            self.passed_this_green = 0

        if self._cooldown(now) > 0:
            return

        # Round-robin scheduling between lanes with waiting vehicles.
        if self.last_green_lane is None:
            search_order = LANES
        else:
            previous = LANES.index(self.last_green_lane)
            search_order = tuple(LANES[(previous + step) % len(LANES)]
                                 for step in range(1, len(LANES) + 1))
        for lane in search_order:
            if self.queues[lane]:
                self.green_lane = lane
                self.last_green_lane = lane
                self.passed_this_green = 0
                LOG.info("%s RED -> GREEN (queue=%d)", lane, len(self.queues[lane]))
                return

    def Join(self, request, context):
        self._require_light(request.lane, context)
        if not request.car_id.strip() or not request.trip_id.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "car_id and trip_id are required")
        with self.lock:
            existing = self.trips.get(request.trip_id)
            if existing:
                if existing.lane != request.lane or existing.car_id != request.car_id:
                    context.abort(grpc.StatusCode.ALREADY_EXISTS,
                                  "trip_id is already used by a different car or lane")
                pos = (list(self.queues[request.lane]).index(request.trip_id) + 1
                       if existing.state == "WAITING" else 0)
                return pb.JoinReply(accepted=True, message="Already registered", queue_position=pos)
            self.trips[request.trip_id] = Trip(lane=request.lane, car_id=request.car_id)
            self.queues[request.lane].append(request.trip_id)
            pos = len(self.queues[request.lane])
            LOG.info("ARRIVE %-12s lane=%s queue_position=%d", request.car_id, request.lane, pos)
            self._advance(time.monotonic())
            return pb.JoinReply(accepted=True, message="Queued", queue_position=pos)

    def RequestPass(self, request, context):
        self._require_light(request.lane, context)
        with self.lock:
            trip = self.trips.get(request.trip_id)
            if trip is None or trip.lane != request.lane:
                context.abort(grpc.StatusCode.NOT_FOUND, "trip_id not found in this lane; call Arrive first")
            self._advance(time.monotonic())

            # Retries with the SAME trip ID do not create a second crossing.
            if trip.state == "CROSSING":
                return pb.Permission(granted=True, state="CROSSING",
                                     message="Same permit (idempotent retry)", crossing_seconds=self.t)
            if trip.state == "DONE":
                return pb.Permission(granted=False, state="DONE", message="Trip already completed")

            queue = self.queues[request.lane]
            pos = list(queue).index(request.trip_id) + 1
            if (request.lane == self.green_lane and self.active_trip is None
                    and queue and queue[0] == request.trip_id):
                queue.popleft()
                trip.state = "CROSSING"
                trip.entered_at = time.monotonic()
                self.active_trip = request.trip_id
                LOG.info("ENTER  %-12s lane=%s t=%.2fs", trip.car_id, trip.lane, self.t)
                return pb.Permission(granted=True, state="CROSSING",
                                     message="Permission granted", crossing_seconds=self.t)

            return pb.Permission(granted=False, state="WAITING", message="Wait for green and your turn",
                                 crossing_seconds=self.t, queue_position=pos)

    def Finish(self, request, context):
        self._require_light(request.lane, context)
        with self.lock:
            trip = self.trips.get(request.trip_id)
            if trip is None or trip.lane != request.lane:
                context.abort(grpc.StatusCode.NOT_FOUND, "Unknown trip_id for this lane")
            if trip.state == "DONE":
                return pb.Ack(ok=True, message="Already completed (idempotent)")
            if trip.state != "CROSSING" or self.active_trip != request.trip_id:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Trip does not hold the crossing permit")
            now = time.monotonic()
            if now - trip.entered_at < self.t:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                              "Car is still crossing; wait the full t seconds")
            trip.state = "DONE"
            self.active_trip = None
            self.last_exit_at = now
            self.total_crossed += 1
            self.passed_this_green += 1
            LOG.info("EXIT   %-12s lane=%s total=%d green_turn_count=%d",
                     trip.car_id, trip.lane, self.total_crossed, self.passed_this_green)
            self._advance(now)
            return pb.Ack(ok=True, message="Crossing completed")

    def Status(self, request, context):
        self._require_light(request.lane, context)
        with self.lock:
            now = time.monotonic()
            self._advance(now)
            active = self.trips.get(self.active_trip) if self.active_trip else None
            return pb.LightStatus(
                lane=request.lane,
                color="GREEN" if self.green_lane == request.lane else "RED",
                waiting=len(self.queues[request.lane]),
                passed_on_green=self.passed_this_green if self.green_lane == request.lane else 0,
                crossing_car=active.car_id if active and active.lane == request.lane else "",
                cooldown_remaining=self._cooldown(now) if self.green_lane is None else 0.0,
            )

    def Snapshot(self, request, context):
        with self.lock:
            now = time.monotonic()
            self._advance(now)
            active = self.trips.get(self.active_trip) if self.active_trip else None
            return pb.JunctionSnapshot(
                lanes=[pb.LaneInfo(
                    lane=lane,
                    color="GREEN" if lane == self.green_lane else "RED",
                    waiting=len(self.queues[lane]),
                    passed_on_green=self.passed_this_green if lane == self.green_lane else 0,
                ) for lane in LANES],
                current_car=active.car_id if active else "",
                current_lane=active.lane if active else "",
                current_trip=self.active_trip or "",
                total_crossed=self.total_crossed,
                cooldown_remaining=self._cooldown(now) if self.green_lane is None else 0.0,
                t_seconds=self.t,
            )


def serve(bind: str, crossing_time: float, max_passes: int, light_ips: dict[str, str]):
    for ip in light_ips.values():
        require_remote(ip)
    service = CoordinatorService(crossing_time, max_passes, light_ips)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=40),
                         options=(("grpc.so_reuseport", 0),))
    rpc.add_CoordinatorServicer_to_server(service, server)
    if server.add_insecure_port(bind) == 0:
        raise RuntimeError(f"Cannot bind coordinator to {bind}")
    server.start()
    LOG.info("COORDINATOR listening on %s | crossing t=%.2fs | max cars=%d",
             bind, crossing_time, max_passes)
    LOG.info("Waiting for heartbeats from lights %s. Press Ctrl+C to stop.", light_ips)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        LOG.info("Stopping coordinator")
        server.stop(2).wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run gRPC three-road intersection coordinator")
    parser.add_argument("--bind", required=True, help="This laptop’s LAN/VPN IPv4 address and port")
    parser.add_argument("--lights", required=True, nargs=3, metavar="LANE=IP",
                        help="IPv4 addresses of the three remote light laptops")
    parser.add_argument("--t", type=float, default=3, help="Seconds for one car to cross AND safety clearance")
    parser.add_argument("--max-passes", type=int, default=10, help="Max cars before yielding to another waiting lane")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    try:
        serve(endpoint(args.bind), args.t, args.max_passes, lane_addresses(args.lights, host_ip))
    except ValueError as exc:
        parser.error(str(exc))
