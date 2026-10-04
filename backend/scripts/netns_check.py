"""Run inside a fresh Linux network namespace before the offline test run.

Brings the loopback interface up (no ``ip`` tool needed) and proves that there
is no route out of the machine, so the test suite really runs without network.
"""

from __future__ import annotations

import errno
import fcntl
import socket
import struct
import sys

SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
IFF_UP = 0x1


def loopback_up() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        request = struct.pack("16sh", b"lo", 0)
        flags = struct.unpack("16sh", fcntl.ioctl(sock, SIOCGIFFLAGS, request))[1]
        fcntl.ioctl(sock, SIOCSIFFLAGS, struct.pack("16sh", b"lo", flags | IFF_UP))


def no_route_out() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        try:
            sock.connect(("192.0.2.1", 80))  # TEST-NET-1, never routable
        except OSError as exc:
            return exc.errno == errno.ENETUNREACH
    return False


def main() -> int:
    loopback_up()
    if not no_route_out():
        print("netns_check: this namespace can still reach the network", file=sys.stderr)
        return 1
    print("netns_check: loopback up, no route out of the machine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
