#!/usr/bin/env python3
"""One car = one independent process / distributed client node.

A car repeatedly chooses a random road, waits for the light, crosses for t
seconds, and after a random delay arrives again at a random road.
"""
import argparse
import random
import sys
import time
import uuid

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc

from network import LANES, endpoint, lane_addresses


def call_with_retry(method, request):
    retries = 0
    while True:
        try:
            return method(request, timeout=6)
        except grpc.RpcError as exc:
            if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED,
                                  grpc.StatusCode.RESOURCE_EXHAUSTED):
                raise
            retries += 1
            if retries == 1 or retries % 5 == 0:
                print(f"  [network] {exc.code().name}; retry #{retries}", flush=True)
            time.sleep(min(2.0, 0.25 * retries))


def drive(car_id, light_addresses, trips, delay_min, delay_max, poll, seed):
    rng = random.Random(seed)
    channels = {lane: grpc.insecure_channel(address) for lane, address in light_addresses.items()}
    lights = {lane: rpc.TrafficLightStub(channel) for lane, channel in channels.items()}
    for lane, channel in channels.items():
        try:
            grpc.channel_ready_future(channel).result(timeout=12)
        except grpc.FutureTimeoutError as exc:
            raise RuntimeError(f"Light {lane} at {light_addresses[lane]} is unreachable") from exc
    print(f"[{car_id}] Online; connected to lights A, B, C", flush=True)

    try:
        for number in range(1, trips + 1):
            time.sleep(rng.uniform(delay_min, delay_max))
            lane = rng.choice(LANES)
            trip_id = str(uuid.uuid4())  # Idempotency key for this visit.
            stub = lights[lane]
            arrived = call_with_retry(stub.Arrive,
                                      pb.Arrival(lane=lane, car_id=car_id, trip_id=trip_id))
            print(f"[{car_id}] Visit {number}/{trips}: arrived at {lane} "
                  f"(queue position {arrived.queue_position})", flush=True)

            last_report = None
            while True:
                # Explicit gRPC status exchange (not a local shared variable).
                status = call_with_retry(stub.Status, pb.Empty())
                permit = call_with_retry(stub.RequestPass,
                                         pb.VehicleRequest(lane=lane, trip_id=trip_id))
                if permit.granted:
                    print(f"[{car_id}] ENTER junction from {lane}: "
                          f"crossing for t={permit.crossing_seconds:.2f}s", flush=True)
                    break
                if permit.state == "DONE":
                    raise RuntimeError("Trip somehow completed before this car crossed")
                current_report = (status.color, permit.queue_position)
                if current_report != last_report:
                    print(f"[{car_id}] {lane}={status.color}, "
                          f"queue position={permit.queue_position} -> WAIT", flush=True)
                    last_report = current_report
                time.sleep(poll + rng.uniform(0, poll * 0.25))

            # The coordinator won't free the junction until this car calls Finish.
            time.sleep(permit.crossing_seconds)
            request = pb.VehicleRequest(lane=lane, trip_id=trip_id)
            while True:
                try:
                    ack = call_with_retry(stub.Finish, request)
                    if ack.ok:
                        break
                except grpc.RpcError as exc:
                    if exc.code() != grpc.StatusCode.FAILED_PRECONDITION:
                        raise
                    time.sleep(0.2)  # clock/network timing: ensure full t elapsed
            print(f"[{car_id}] EXIT junction from {lane} (visit {number} complete)", flush=True)
    finally:
        for channel in channels.values():
            channel.close()
    print(f"[{car_id}] Finished all {trips} visits", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One independently running vehicle node")
    parser.add_argument("--lights", required=True, nargs=3, metavar="LANE=IP:PORT",
                        help="Exactly three reachable light addresses: A=IP:PORT B=IP:PORT C=IP:PORT")
    parser.add_argument("--id", default=f"car-{uuid.uuid4().hex[:6]}", help="Human-readable car name")
    parser.add_argument("--trips", type=int, default=5, help="How many times this car returns to the junction")
    parser.add_argument("--delay-min", type=float, default=0.2, help="Minimum random delay before each arrival")
    parser.add_argument("--delay-max", type=float, default=2.0, help="Maximum random delay before each arrival")
    parser.add_argument("--poll", type=float, default=0.3, help="Seconds between green-light checks")
    parser.add_argument("--seed", type=int, help="Optional deterministic random seed")
    args = parser.parse_args()
    if (args.trips < 1 or args.poll <= 0 or args.delay_min < 0 or
            args.delay_max < args.delay_min):
        parser.error("Require trips >= 1, poll > 0, and 0 <= delay-min <= delay-max")
    try:
        drive(args.id, lane_addresses(args.lights, endpoint), args.trips,
              args.delay_min, args.delay_max, args.poll, args.seed)
    except (ValueError, RuntimeError, grpc.RpcError) as exc:
        print(f"[{args.id}] ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
