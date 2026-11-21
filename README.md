# Distributed traffic-light junction (Python + gRPC)

The Group 5 junction simulation runs on **four or five laptops** on the same reachable network. One laptop runs the coordinator and three other laptops each run one traffic light. Three or more independent vehicle processes can run on the coordinator laptop or on an optional fifth laptop.

Python **3.10 or newer** is recommended.

## 1. Architecture

```text
CAR 1 process ---gRPC---> [ LIGHT A process ] ---gRPC---+
CAR 2 process ---gRPC---> [ LIGHT B process ] ---gRPC---+--> [ COORDINATOR process ]
CAR 3 process ---gRPC---> [ LIGHT C process ] ---gRPC---+         |
CAR N process ---gRPC---> (its chosen light)               serialized decisions
                                                            /  |  \
                                                     queues A   B   C
MONITOR process ---gRPC------------------------------------> snapshot
```

Each car **chooses a random road**, joins its lane's FIFO queue, asks for status via gRPC (`car -> light -> coordinator`), requests a crossing permit, spends `t` seconds crossing, notifies completion via gRPC, and returns after a random delay on a **new random road**. A car can make multiple visits; each is identified by a unique `trip_id` for idempotency.

- **Safety:** One lane GREEN at a time. Additionally, the coordinator grants the physical junction to only one car at a time. All critical state changes are protected by one lock.
- **Switching:** If another lane has waiting cars, the active light changes GREEN to RED either after its queue empties or when **10 cars have completed** during the current green turn (`--max-passes 10`). An in-progress car always finishes first.
- **Red-to-green delay:** A different lane cannot turn GREEN until **at least `t` seconds after the last car left** the intersection. All lights remain RED during the clearance interval.
- **Fairness:** FIFO within each lane, round-robin selection among lanes with queued vehicles.
- **Distributed messaging:** No direct shared memory exists between the light processes, car processes, and coordinator. Each status check and crossing request uses real gRPC network calls.
- **Idempotency:** Duplicate Arrive, RequestPass, or Finish RPCs for a trip do not cause duplicate crossings.

**Assumptions / failure behavior:** The coordinator is the single authority (centralized synchronization, not consensus). A granted car must eventually report `Finish`; if it crashes mid-crossing, the coordinator **stops further crossings** rather than risk a collision. This is deliberately fail-safe, and restart/recovery would require additional sensors/leases and a failure protocol. Network links must be reachable; the demo uses plaintext gRPC and is intended for a trusted local LAN / private VPN only.

## 2. Install on every computer

Copy the project files to each laptop. Open Terminal in this directory.

**macOS / Linux:**

```bash
cd grpc_traffic_lights
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
cd grpc_traffic_lights
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

> If PowerShell blocks activation, run `\.venv\Scripts\python.exe` instead of `python`, or use Command Prompt's `.venv\Scripts\activate.bat`.
>
> Generated `traffic_pb2.py` and `traffic_pb2_grpc.py` are **already included**, so you do **not** need to install grpcio-tools or compile the `.proto` file.

## 3. Run across FOUR or FIVE laptops

**Example network (replace IPs with your own):**

| Computer | Role | LAN IP | Listening port |
|---|---|---|---|
| Laptop 1 | Coordinator | `192.168.1.10` | 50050 |
| Laptop 2 | Light A | `192.168.1.11` | 50051 |
| Laptop 3 | Light B | `192.168.1.12` | 50051 |
| Laptop 4 | Light C | `192.168.1.13` | 50051 |
| Laptop 5 (or any of the above) | Cars, monitor | Any reachable IP | No listening port needed |

**1) Laptop 1: start the coordinator FIRST:**

```bash
python coordinator.py --bind 192.168.1.10:50050 --lights A=192.168.1.11 B=192.168.1.12 C=192.168.1.13 --t 3 --max-passes 10
```

**2) Laptop 2: start Light A:**

```bash
python traffic_light.py --lane A --coordinator 192.168.1.10:50050
```

**3) Laptop 3: start Light B:**

```bash
python traffic_light.py --lane B --coordinator 192.168.1.10:50050
```

**4) Laptop 4: start Light C:**

```bash
python traffic_light.py --lane C --coordinator 192.168.1.10:50050
```

Each light listens on TCP 50051, with one light process per laptop. The coordinator checks each light’s connection against the configured lane IP. Wait for all three lights to log that they registered before starting cars. If a light stops sending heartbeats for five seconds, the coordinator pauses new crossings until all three lights are back. A car with a permit can still finish.

**5) Laptop 5 (or Laptop 1): launch six separate car processes:**

```bash
python spawn_cars.py --cars 6 --trips 5 --lights A=192.168.1.11:50051 B=192.168.1.12:50051 C=192.168.1.13:50051
```

**6) On any laptop, open the optional dashboard:**

```bash
python monitor.py --coordinator 192.168.1.10:50050
```

Use `Ctrl+C` to stop the servers. On different computers, each terminal must stay running while the demo is active.

### Run individual vehicles on different laptops instead

```bash
python vehicle.py --id car-1 --trips 5 --lights A=192.168.1.11:50051 B=192.168.1.12:50051 C=192.168.1.13:50051
```

Run the same command in another terminal/computer with `--id car-2`, `--id car-3`, etc. Each process has its own connections and its own randomized visits. Use `--delay-min 0 --delay-max 0.5` to create queue contention quickly.

## 4. Finding your computer's reachable address

On **macOS Wi-Fi** (typically `en0`):

```bash
ipconfig getifaddr en0
```

If empty, inspect `ifconfig` to find the active interface. On **Windows**, run `ipconfig` and look for the active Wi-Fi/Ethernet IPv4 Address. On **Linux**, run `hostname -I` or `ip addr`.

**Connectivity checklist:**

1. All devices must be on the **same reachable local network** (a personal hotspot/private Wi-Fi works). Some university/guest networks isolate devices; if so, use a private hotspot or a private mesh VPN such as Tailscale.
2. **Use the real LAN/VPN IPv4 addresses** seen by the other laptops. Each light must reach the coordinator from the IP configured for its lane.
3. Start the coordinator before lights, and all lights before vehicles.
4. Ensure firewalls allow **inbound TCP 50050** to the coordinator and **inbound TCP 50051** to each separate light.
5. Check `ping 192.168.1.10` (if ICMP is allowed), or on macOS/Linux check `nc -vz 192.168.1.10 50050`. On Windows, `Test-NetConnection 192.168.1.10 -Port 50050`.
6. Do not expose these unauthenticated plaintext services directly to the public internet.

## 5. Testing the assignment rules

```bash
python -m unittest -v test_protocol.py
```

The test harness uses local sockets to check the gRPC protocol and simulated network peers to check deployment rules. It covers:

- only one GREEN light at any time;
- no other car gets permission during an active crossing;
- a `Finish` cannot happen before the full `t`;
- all-red cooldown after the last car exits;
- with another waiting lane, switch after **exactly 10 completed vehicles**, even when cars remain on the first lane;
- idempotent retries (no duplicates);
- six concurrent vehicle threads completing eighteen visits;
- rejection of duplicate or loopback light addresses and connections from the wrong lane IP;
- permit availability when all three lights are online, and pausing when a heartbeat expires.

## 6. Files included

| File | Purpose |
|---|---|
| `traffic.proto` | gRPC request/response contracts and services |
| `traffic_pb2.py` | Precompiled protobuf message classes |
| `traffic_pb2_grpc.py` | Precompiled gRPC client stubs and server adapters |
| `coordinator.py` | Thread-safe centralized scheduling and synchronization |
| `traffic_light.py` | Independently running traffic-light node / gRPC server |
| `vehicle.py` | Independently running vehicle node / gRPC client |
| `spawn_cars.py` | Launch 3+ car processes simultaneously |
| `monitor.py` | Live gRPC-based terminal dashboard |
| `network.py` | Validate the LAN addresses used by the coordinator and lights |
| `test_protocol.py` | Automated integration and safety tests |
| `requirements.txt` | Runtime libraries |

### Optional: edit and recompile the `.proto`

Only necessary if you change the RPC schema:

```bash
python -m pip install grpcio-tools
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. traffic.proto
```

This replaces the included generated stub files with ones generated by your installed grpcio-tools version.

## Notes for your distributed-systems presentation

- **Mutual exclusion:** The coordinator's lock serializes competing RPC requests; a single `green_lane` variable and an `active_trip` permit prevent conflicting movements.
- **Message passing:** Vehicle and traffic-light nodes have no shared-memory state; every remote status check and permit uses unary gRPC messages.
- **Synchronization:** GREEN->RED->(at least `t` seconds since exit)->GREEN, where the deadline uses the coordinator's monotonic clock (no clock synchronization between laptops required).
- **Fairness / starvation avoidance:** FIFO and round-robin; an active lane must yield after 10 completed crossings when another lane waits.
- **RPC retries:** A stable `trip_id` makes Join, RequestPass, and Finish idempotent, so a lost reply doesn't count a crossing twice.
- **Failure mode:** Central coordinator is a single point of failure. If a car vanishes after a permit, the simulation fails closed. This is intentional for safety, but not a fault-tolerant consensus algorithm.
