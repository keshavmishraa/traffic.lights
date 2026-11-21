#!/usr/bin/env python3
"""Real gRPC protocol tests, including concurrency and safety invariants.

Run: python -m unittest -v test_protocol.py
"""
from concurrent import futures
import threading
import time
import unittest
from unittest.mock import Mock, patch

import grpc
import traffic_pb2 as pb
import traffic_pb2_grpc as rpc
from coordinator import CoordinatorService
from network import HEARTBEAT_TIMEOUT, host_ip, lane_addresses
from traffic_light import LightService


LIGHT_IPS = {"A": "192.168.1.11", "B": "192.168.1.12", "C": "192.168.1.13"}


class JunctionHarness:
    def __init__(self, t=0.04, max_passes=10):
        self.coordinator_server = grpc.server(futures.ThreadPoolExecutor(max_workers=30))
        self.service = CoordinatorService(t, max_passes, LIGHT_IPS)
        # Exercise scheduling over real gRPC with local test sockets.
        self.service._require_light = Mock()
        self.service._lights_ready = Mock(return_value=True)
        rpc.add_CoordinatorServicer_to_server(self.service, self.coordinator_server)
        port = self.coordinator_server.add_insecure_port("127.0.0.1:0")
        self.coordinator_server.start()
        self.coordinator_channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        self.coordinator = rpc.CoordinatorStub(self.coordinator_channel)
        self.servers = []
        self.channels = []
        self.lights = {}
        for lane in "ABC":
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
            rpc.add_TrafficLightServicer_to_server(
                LightService(lane, self.coordinator_channel), server)
            lport = server.add_insecure_port("127.0.0.1:0")
            server.start()
            self.servers.append(server)
            channel = grpc.insecure_channel(f"127.0.0.1:{lport}")
            self.channels.append(channel)
            self.lights[lane] = rpc.TrafficLightStub(channel)
        self.t = t

    def join(self, lane, name):
        result = self.lights[lane].Arrive(
            pb.Arrival(lane=lane, car_id=name, trip_id=name), timeout=3)
        assert result.accepted
        return result

    def request(self, lane, name):
        return self.lights[lane].RequestPass(
            pb.VehicleRequest(lane=lane, trip_id=name), timeout=3)

    def finish(self, lane, name):
        return self.lights[lane].Finish(
            pb.VehicleRequest(lane=lane, trip_id=name), timeout=3)

    def snap(self):
        return self.coordinator.Snapshot(pb.Empty(), timeout=3)

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.snap()
            if predicate(snapshot):
                return snapshot
            time.sleep(0.004)
        raise AssertionError(f"Condition not reached: {self.snap()}")

    def close(self):
        for channel in self.channels:
            channel.close()
        self.coordinator_channel.close()
        for server in self.servers:
            server.stop(0).wait()
        self.coordinator_server.stop(0).wait()


class TestDeployment(unittest.TestCase):
    def test_loopback_and_repeated_ips_are_rejected(self):
        for entries in (["A=127.0.0.1", "B=192.168.1.12", "C=192.168.1.13"],
                        ["A=192.168.1.11", "B=192.168.1.11", "C=192.168.1.13"]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                lane_addresses(entries, host_ip)

    def test_heartbeat_requires_the_configured_peer_for_the_lane(self):
        service = CoordinatorService(1, 10, LIGHT_IPS)
        for peer in ("ipv4:127.0.0.1:60000", f"ipv4:{LIGHT_IPS['B']}:60000"):
            with self.subTest(peer=peer):
                context = self.peer(peer)
                with self.assertRaises(grpc.RpcError):
                    service.Heartbeat(pb.LightRequest(lane="A"), context)
                context.abort.assert_called_once_with(grpc.StatusCode.PERMISSION_DENIED,
                                                      f"Lane A must connect from {LIGHT_IPS['A']}")
        self.assertFalse(service.last_heartbeat)

    @staticmethod
    def peer(address):
        context = Mock(spec=grpc.ServicerContext)
        context.peer.return_value = address
        context.abort.side_effect = grpc.RpcError
        return context

    def test_crossings_wait_for_all_three_lights_and_pause_after_timeout(self):
        service = CoordinatorService(1, 10, LIGHT_IPS)
        peers = {lane: self.peer(f"ipv4:{ip}:60000") for lane, ip in LIGHT_IPS.items()}
        arrival = pb.Arrival(lane="A", car_id="car", trip_id="first")
        request = pb.VehicleRequest(lane="A", trip_id="first")
        with patch("coordinator.time.monotonic", return_value=100) as clock:
            for lane in "AB":
                service.Heartbeat(pb.LightRequest(lane=lane), peers[lane])
            service.Join(arrival, peers["A"])
            self.assertFalse(service.RequestPass(request, peers["A"]).granted)
            service.Heartbeat(pb.LightRequest(lane="C"), peers["C"])
            self.assertTrue(service.RequestPass(request, peers["A"]).granted)
            clock.return_value += HEARTBEAT_TIMEOUT
            self.assertTrue(service.Finish(request, peers["A"]).ok)

            arrival.trip_id = request.trip_id = "second"
            service.Join(arrival, peers["A"])
            for lane in "AB":
                service.Heartbeat(pb.LightRequest(lane=lane), peers[lane])
            self.assertFalse(service.RequestPass(request, peers["A"]).granted)
            self.assertTrue(all(lane.color == "RED"
                                for lane in service.Snapshot(pb.Empty(), peers["A"]).lanes))
            clock.return_value += 1
            service.Heartbeat(pb.LightRequest(lane="C"), peers["C"])
            self.assertTrue(service.RequestPass(request, peers["A"]).granted)


class TestTrafficLights(unittest.TestCase):
    def test_cooldown_one_green_and_message_exchange(self):
        h = JunctionHarness(t=0.15)
        try:
            h.join("A", "a1")
            self.assertEqual(h.lights["A"].Status(pb.Empty()).color, "GREEN")
            h.join("B", "b1")
            self.assertTrue(h.request("A", "a1").granted)
            self.assertFalse(h.request("B", "b1").granted)
            with self.assertRaises(grpc.RpcError) as captured:
                h.finish("A", "a1")
            self.assertEqual(captured.exception.code(), grpc.StatusCode.FAILED_PRECONDITION)
            time.sleep(0.165)
            self.assertTrue(h.finish("A", "a1").ok)
            self.assertTrue(all(lane.color == "RED" for lane in h.snap().lanes))
            self.assertFalse(h.request("B", "b1").granted)
            h.wait_for(lambda s: next(x for x in s.lanes if x.lane == "B").color == "GREEN")
            self.assertTrue(h.request("B", "b1").granted)
            time.sleep(0.16)
            h.finish("B", "b1")
            self.assertEqual(h.snap().total_crossed, 2)
        finally:
            h.close()

    def test_ten_completed_cars_causes_round_robin_switch(self):
        h = JunctionHarness(t=0.022, max_passes=10)
        try:
            for index in range(1, 12):
                h.join("A", f"a{index}")
            h.join("B", "b1")
            for index in range(1, 11):
                name = f"a{index}"
                self.assertTrue(h.request("A", name).granted)
                time.sleep(0.025)
                h.finish("A", name)
            snap = h.snap()
            self.assertTrue(all(light.color == "RED" for light in snap.lanes))
            self.assertEqual(next(x for x in snap.lanes if x.lane == "A").waiting, 1)
            h.wait_for(lambda s: next(x for x in s.lanes if x.lane == "B").color == "GREEN")
            self.assertFalse(h.request("A", "a11").granted)
            self.assertTrue(h.request("B", "b1").granted)
            time.sleep(0.026)
            h.finish("B", "b1")
            h.wait_for(lambda s: next(x for x in s.lanes if x.lane == "A").color == "GREEN")
            self.assertTrue(h.request("A", "a11").granted)
            time.sleep(0.027)
            h.finish("A", "a11")
            self.assertEqual(h.snap().total_crossed, 12)
        finally:
            h.close()

    def test_duplicate_requests_do_not_duplicate_crossings(self):
        h = JunctionHarness(t=0.025)
        try:
            h.join("C", "c1")
            h.join("C", "c1")  # idempotent retry
            self.assertEqual(h.snap().lanes[2].waiting, 1)
            self.assertTrue(h.request("C", "c1").granted)
            self.assertTrue(h.request("C", "c1").granted)
            time.sleep(0.03)
            h.finish("C", "c1")
            self.assertTrue(h.finish("C", "c1").ok)
            self.assertEqual(h.snap().total_crossed, 1)
        finally:
            h.close()

    def test_many_concurrent_vehicle_nodes_preserve_safety(self):
        h = JunctionHarness(t=0.012, max_passes=3)
        errors = []
        done = threading.Event()
        greens_observed = []

        def watcher():
            while not done.is_set():
                try:
                    snap = h.snap()
                    greens_observed.append(sum(x.color == "GREEN" for x in snap.lanes))
                except Exception as exc:
                    errors.append(exc)
                time.sleep(0.002)

        def car(i):
            try:
                for round_number in range(3):
                    lane = "ABC"[(i + round_number) % 3]
                    name = f"car{i}-visit{round_number}"
                    h.join(lane, name)
                    for attempt in range(2500):
                        if h.request(lane, name).granted:
                            break
                        time.sleep(0.003)
                    else:
                        raise AssertionError(f"Timed out waiting for {name}")
                    time.sleep(0.017)
                    h.finish(lane, name)
            except Exception as exc:
                errors.append(exc)

        monitor = threading.Thread(target=watcher)
        workers = [threading.Thread(target=car, args=(i,)) for i in range(6)]
        try:
            monitor.start()
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=12)
            self.assertTrue(all(not w.is_alive() for w in workers), "A vehicle thread got stuck")
            self.assertFalse(errors, str(errors))
            self.assertEqual(h.snap().total_crossed, 18)
            self.assertTrue(greens_observed)
            self.assertLessEqual(max(greens_observed), 1)
        finally:
            done.set()
            monitor.join(timeout=2)
            h.close()


if __name__ == "__main__":
    unittest.main()
