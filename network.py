"""IPv4 addresses for the four-laptop junction."""
import errno
import ipaddress
import socket

LANES = ("A", "B", "C")
HEARTBEAT_INTERVAL = 1
HEARTBEAT_TIMEOUT = 5


def host_ip(value):
    ip = ipaddress.IPv4Address(value)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError(f"Use a reachable LAN/VPN IPv4 address, got {value!r}")
    return str(ip)


def endpoint(value):
    host, _, port = value.rpartition(":")
    host = host_ip(host)
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError(f"Expected an IPv4 address and port, got {value!r}")
    return f"{host}:{int(port)}"


def lane_addresses(entries, parse_address):
    addresses = {}
    for entry in entries:
        lane, _, address = entry.partition("=")
        if lane not in LANES or lane in addresses:
            raise ValueError("Supply one address for each of A, B, and C")
        addresses[lane] = parse_address(address)
    if addresses.keys() != set(LANES):
        raise ValueError("Supply one address for each of A, B, and C")
    if len({address.split(":")[0] for address in addresses.values()}) != len(LANES):
        raise ValueError("Each light must use a different laptop IP")
    return addresses


def require_remote(ip):
    # Binding an ephemeral port checks for local IP aliases as well as the
    # primary address, without relying on interface names or shell commands.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((ip, 0))
        except OSError as exc:
            if exc.errno == errno.EADDRNOTAVAIL or getattr(exc, "winerror", None) == 10049:
                return
            raise
    raise ValueError(f"{ip} is local. Put the coordinator and each light on separate laptops.")
