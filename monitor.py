#!/usr/bin/env python3
"""Read-only terminal dashboard (also communicates via gRPC)."""
import argparse
import time

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc

from network import endpoint


def main():
    parser = argparse.ArgumentParser(description="Monitor the three-road junction")
    parser.add_argument("--coordinator", required=True)
    parser.add_argument("--refresh", type=float, default=0.5)
    parser.add_argument("--no-clear", action="store_true", help="Print successive snapshots instead of refreshing screen")
    args = parser.parse_args()
    try:
        args.coordinator = endpoint(args.coordinator)
    except ValueError as exc:
        parser.error(str(exc))
    if args.refresh <= 0:
        parser.error("refresh must be > 0")
    channel = grpc.insecure_channel(args.coordinator)
    stub = rpc.CoordinatorStub(channel)
    try:
        while True:
            try:
                snap = stub.Snapshot(pb.Empty(), timeout=3)
            except grpc.RpcError as exc:
                print(f"Coordinator unavailable: {exc.code().name}. Retrying...")
                time.sleep(2)
                continue
            if not args.no_clear:
                print("\033[2J\033[H", end="")
            print("=== DISTRIBUTED gRPC TRAFFIC LIGHTS ===")
            print(f"Coordinator: {args.coordinator}  |  t={snap.t_seconds:g}s  "
                  f"|  Total passed: {snap.total_crossed}")
            print("------------------------------------")
            for light in snap.lanes:
                marker = "[GREEN]" if light.color == "GREEN" else "[ RED ]"
                print(f" Lane {light.lane}  {marker}   Waiting: {light.waiting:2d}  "
                      f"Passed during green: {light.passed_on_green}")
            print("------------------------------------")
            print(f"Crossing now: {snap.current_car or '(none)'} "
                  f"{('from lane ' + snap.current_lane) if snap.current_lane else ''}")
            if snap.cooldown_remaining > 0:
                print(f"ALL RED: wait {snap.cooldown_remaining:.2f}s for clearance")
            print("Ctrl+C to quit (the simulation keeps running).", flush=True)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        pass
    finally:
        channel.close()


if __name__ == "__main__":
    main()
