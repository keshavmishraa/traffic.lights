#!/usr/bin/env python3
"""Launch many independent vehicle.py processes on the SAME computer."""
import argparse
import subprocess
import sys
import time

from network import endpoint, lane_addresses


def main():
    parser = argparse.ArgumentParser(description="Spawn multiple independent car processes")
    parser.add_argument("--lights", required=True, nargs=3, metavar="LANE=IP:PORT")
    parser.add_argument("--cars", type=int, default=6)
    parser.add_argument("--trips", type=int, default=4)
    parser.add_argument("--delay-min", type=float, default=0.2)
    parser.add_argument("--delay-max", type=float, default=2.0)
    parser.add_argument("--poll", type=float, default=0.3)
    args = parser.parse_args()
    if args.cars < 3:
        parser.error("The assignment requires at least three vehicles (--cars 3 or more)")
    try:
        lane_addresses(args.lights, endpoint)
    except ValueError as exc:
        parser.error(str(exc))
    children = []
    try:
        for index in range(args.cars):
            cmd = [sys.executable, "-u", "vehicle.py",
                   "--id", f"car-{index + 1}",
                   "--trips", str(args.trips),
                   "--lights", *args.lights,
                   "--delay-min", str(args.delay_min),
                   "--delay-max", str(args.delay_max),
                   "--poll", str(args.poll)]
            child = subprocess.Popen(cmd)
            children.append(child)
            time.sleep(0.1)
        print(f"\nStarted {len(children)} independent car processes.\n", flush=True)
        codes = [child.wait() for child in children]
        if any(code != 0 for code in codes):
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping cars...", flush=True)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            child.wait()
        sys.exit(130)


if __name__ == "__main__":
    main()
