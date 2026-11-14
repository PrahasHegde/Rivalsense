"""Inspect local HTTP redirects, not the provider's independent requests.

IP pinning protects only preflight connections. Context.dev resolves DNS and
follows navigation separately. Checking its final URL happens after retrieval
and cannot prevent unsafe intermediate requests in the remote browser.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from app.schemas.prices import ExtractRequest


class UnsafeURL(ValueError):
    pass


def public_destination(url: str) -> tuple[str, str]:
    try:
        normalized = str(ExtractRequest(url=url).url)
        host = urlsplit(normalized).hostname
        if host:
            host = host.rstrip(".")
        if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
            raise ValueError()
        # No single-label intranet names; IPv6 literals are checked below.
        if "." not in host and ":" not in host:
            raise ValueError()
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
        if not ips or any(not ip.is_global or ip.is_multicast for ip in ips):
            raise ValueError()
        if any(isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None for ip in ips):
            raise ValueError()
        return normalized, str(ips[0])
    except (ValueError, OSError):
        raise UnsafeURL("URL must resolve only to public HTTPS destinations") from None


def check_redirects(url: str) -> str:
    # Pin preflight connections to checked IPs; preserve TLS hostname verification.
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            url, address = public_destination(url)
            host = urlsplit(url).hostname
            target = httpx.URL(url).copy_with(host=address)
            with client.stream("GET", target, headers={"Host": host},
                               extensions={"sni_hostname": host}) as response:
                if response.status_code not in (301, 302, 303, 307, 308):
                    return url
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURL("Redirect has no destination")
                url = urljoin(url, location)
        raise UnsafeURL("Too many redirects")
