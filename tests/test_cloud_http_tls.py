"""Real loopback TLS proving public-address pinning retains origin hostname checks.

Only the test NetworkBackend maps the asserted public literal to loopback. The
runtime address policy, certificate validation and SNI implementation are used
unchanged, with one temporary CA trusted only by the fixture client context.
"""
from __future__ import annotations

import asyncio
import ssl
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpcore
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from httpcore._backends.anyio import AnyIOBackend
from test_cloud_http import PUBLIC_IP, environment, permitted

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_profile import digest, validate_profile
from hypertest.cloud.http_transport import HttpsTransport


def certificate_files(tmp_path):
    ca_key = ec.generate_private_key(ec.SECP256R1())
    server_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic HTTPS fixture CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
            encipher_only=None, decipher_only=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256()))
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.example.invalid")])
    certificate = (x509.CertificateBuilder().subject_name(server_name).issuer_name(ca_name)
        .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=None, decipher_only=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.example.invalid")]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    ca_path, cert_path, key_path = (tmp_path / name for name in ("fixture-ca.pem", "fixture-server.pem", "fixture-key.pem"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    return ca_path, cert_path, key_path


class PublicPinToFixtureBackend:
    """No runtime seam accepts this mapping from a model or project resource."""
    def __init__(self, port):
        self.port = port
        self.calls = []
        self.backend = AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        assert host == PUBLIC_IP and port == 443
        return await self.backend.connect_tcp("127.0.0.1", self.port, timeout=timeout,
            local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, *args, **kwargs):
        raise AssertionError("Unexpected Unix transport")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@asynccontextmanager
async def tls_fixture(cert_path, key_path):
    received = []
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert_path), str(key_path))
    async def handle(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
            received.append(request)
            body = b'{"tls":"synthetic fixture only"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=tls)
    try:
        yield server.sockets[0].getsockname()[1], received
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("fault", [None, "wrong-hostname", "untrusted-ca"])
async def test_actual_tls_uses_original_hostname_for_certificate_validation_with_public_tcp_pin(tmp_path, fault):
    ca_path, cert_path, key_path = certificate_files(tmp_path)
    selected = validate_profile(environment())
    if fault == "wrong-hostname":
        raw = environment()
        raw["host"] = "wrong.example.invalid"
        catalog = {key: value for key, value in raw["https_access"].items() if key != "catalog_sha256"}
        raw["https_access"]["catalog_sha256"] = digest({**catalog, "target": "https://wrong.example.invalid:443"})
        selected = validate_profile(raw)
    trusted = ssl.create_default_context(cafile=str(ca_path)) if fault != "untrusted-ca" else ssl.create_default_context()
    assert trusted.check_hostname and trusted.verify_mode == ssl.CERT_REQUIRED
    async with tls_fixture(cert_path, key_path) as (port, received):
        backend = PublicPinToFixtureBackend(port)
        # This is the same HTTPX/httpcore TLS path as the runtime. Only the TCP
        # destination backend is substituted, after it asserts the frozen pin.
        transport = httpx.AsyncHTTPTransport(verify=trusted, retries=0, trust_env=False)
        transport._pool = httpcore.AsyncConnectionPool(ssl_context=trusted, network_backend=backend,
            retries=0, max_connections=1, max_keepalive_connections=0)
        async def resolver(host, requested_port):
            assert host == selected.host and requested_port == 443
            return [PUBLIC_IP]
        guarded = HttpsTransport(resolver=resolver, transport=transport, tls_context=trusted)
        if fault:
            with pytest.raises(CloudBlocked) as error:
                await guarded.send(selected, selected.resources[0], timeout=2, before_send=permitted)
            assert error.value.code == "HTTPS_TRANSPORT_UNKNOWN"
            assert received == []
        else:
            result = await guarded.send(selected, selected.resources[0], timeout=2, before_send=permitted)
            assert result.status == 200 and result.body == b'{"tls":"synthetic fixture only"}'
            assert len(received) == 1 and b"Host: api.example.invalid:443\r\n" in received[0]
        assert backend.calls == [(PUBLIC_IP, 443)]
