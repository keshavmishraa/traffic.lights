#!/usr/bin/env python3
"""Independent traffic-light node: run one instance per A/B/C lane.

A vehicle talks to THIS light over gRPC. The light exchanges messages with
coordinator to get an authoritative state/permit; no local stale green cache.
"""
import argparse
from concurrent import futures
import logging
import time

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc

from network import HEARTBEAT_INTERVAL, endpoint, require_remote

LOG = logging.getLogger("traffic-light")
LIGHT_BIND = "0.0.0.0:50051"


class LightService:
    def __init__(self, lane: str, channel):
        self.lane = lane
        self.coordinator = rpc.CoordinatorStub(channel)

    def _forward(self, fn, request, context):
        try:
            return fn(request, timeout=5)
        except grpc.RpcError as exc:
            context.abort(exc.code(), f"Coordinator: {exc.details()}")

    def _check_lane(self, lane, context):
        if lane != self.lane:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          f"You connected to light {self.lane}; requested lane {lane}")

    def Arrive(self, request, context):
        self._check_lane(request.lane, context)
        response = self._forward(self.coordinator.Join, request, context)
        LOG.info("ARRIVE %-12s queue_position=%d", request.car_id, response.queue_position)
        return response

    def RequestPass(self, request, context):
        self._check_lane(request.lane, context)
        response = self._forward(self.coordinator.RequestPass, request, context)
        if response.granted and response.message == "Permission granted":
            LOG.info("GRANT trip=%s", request.trip_id[:8])
        return response

    def Finish(self, request, context):
        self._check_lane(request.lane, context)
        response = self._forward(self.coordinator.Finish, request, context)
        LOG.info("FINISH trip=%s", request.trip_id[:8])
        return response

    def Status(self, request, context):
        # Even a status read requires messages: car -> light -> coordinator.
        return self._forward(self.coordinator.Status, pb.LightRequest(lane=self.lane), context)


def serve(lane: str, coordinator_address: str):
    require_remote(coordinator_address.split(":")[0])
    with grpc.insecure_channel(coordinator_address) as channel:
        service = LightService(lane, channel)
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=30),
                             options=(("grpc.so_reuseport", 0),))
        rpc.add_TrafficLightServicer_to_server(service, server)
        # A shared port with reuse disabled allows one light per network stack.
        server.add_insecure_port(LIGHT_BIND)
        server.start()
        try:
            request = pb.LightRequest(lane=lane)
            service.coordinator.Heartbeat(request, timeout=10, wait_for_ready=True)
            LOG.info("LIGHT %s registered at %s; coordinator=%s", lane, LIGHT_BIND, coordinator_address)
            while True:
                time.sleep(HEARTBEAT_INTERVAL)
                try:
                    service.coordinator.Heartbeat(request, timeout=2)
                except grpc.RpcError as exc:
                    if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                        raise
                    LOG.warning("Heartbeat failed: %s", exc.details())
        except grpc.RpcError as exc:
            raise SystemExit(f"Coordinator {coordinator_address}: {exc.details()}") from exc
        except KeyboardInterrupt:
            LOG.info("Stopping light %s", lane)
        finally:
            server.stop(2).wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one independent gRPC traffic-light server")
    parser.add_argument("--lane", choices=("A", "B", "C"), required=True)
    parser.add_argument("--coordinator", required=True, help="Coordinator's reachable IP:port")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [light-%(name)s] %(message)s", datefmt="%H:%M:%S")
    try:
        serve(args.lane, endpoint(args.coordinator))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
