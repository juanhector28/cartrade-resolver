"""Conservative URL checks for the generic listing importer.

This is defense in depth, not a replacement for blocking private destinations
at the deployment egress/proxy layer (DNS rebinding remains possible).
"""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlsplit


def is_public_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        if p.username is not None or p.password is not None:
            return False
        if p.port not in (None, 80, 443):
            return False
        host = p.hostname.rstrip(".").lower()
        if host in ("localhost", "localhost.localdomain") or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or any(not part for part in host.split(".")):
                return False
            return True
        return ip.is_global
    except (ValueError, TypeError):
        return False


def public_dns_addresses(hostname: str) -> bool:
    """Refuse DNS names pointing to nonpublic addresses or having no results."""
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(addr[4][0]).is_global for addr in addresses)
    except (OSError, ValueError):
        return False
