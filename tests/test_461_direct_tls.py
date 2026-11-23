from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import run
from backend.api import owner_session as owner


@pytest.fixture
def startup(monkeypatch):
    settings = SimpleNamespace(APP_ENV="development", LOG_LEVEL="INFO",
                               HOME_HUB_SERVER_TLS_CERTFILE=None,
                               HOME_HUB_SERVER_TLS_KEYFILE=None, HOME_HUB_SERVER_TLS_HOST="127.0.0.1",
                               HOME_HUB_SERVER_TLS_PORT=8443)
    server = Mock()
    monkeypatch.setattr(run, "settings", settings)
    monkeypatch.setattr(run.uvicorn, "run", server)
    return settings, server


def test_default_listener_unchanged(startup):
    _, server = startup
    run.main()
    server.assert_called_once_with("backend.main:app", host="0.0.0.0", port=8000,
                                  reload=True, log_level="info", ws_ping_interval=30,
                                  ws_ping_timeout=60)


def test_tls_pair_validated_and_server_configured(startup, monkeypatch, tmp_path):
    settings, server = startup
    settings.APP_ENV = "production"
    cert, key = tmp_path / "cert", tmp_path / "key"
    cert.touch()
    key.touch()
    settings.HOME_HUB_SERVER_TLS_CERTFILE = str(cert)
    settings.HOME_HUB_SERVER_TLS_KEYFILE = str(key)
    context = Mock()
    monkeypatch.setattr(run.ssl, "SSLContext", Mock(return_value=context))
    dual = Mock()
    monkeypatch.setattr(run, "DualTransportServer", dual)
    run.main()
    server.assert_not_called()
    config, actual_context, host, port = dual.call_args.args
    assert (config.host, config.port, config.proxy_headers, config.workers) == ("0.0.0.0", 8000, False, 1)
    assert (actual_context, host, port) == (context, "127.0.0.1", 8443)
    assert context.load_cert_chain.call_args.args == (str(cert), str(key))
    with pytest.raises(ValueError):
        context.load_cert_chain.call_args.kwargs["password"]()
    dual.return_value.run.assert_called_once()


@pytest.mark.parametrize("cert,key", [("cert", None), (None, "key"), ("", ""),
                                        (" ", "key"), ("missing", "missing")])
def test_bad_pair_never_binds(startup, cert, key):
    settings, server = startup
    settings.APP_ENV = "production"
    settings.HOME_HUB_SERVER_TLS_CERTFILE = cert
    settings.HOME_HUB_SERVER_TLS_KEYFILE = key
    with pytest.raises(ValueError):
        run.main()
    server.assert_not_called()


def test_invalid_material_never_binds_or_leaks(startup, monkeypatch, tmp_path):
    settings, server = startup
    cert, key = tmp_path / "cert", tmp_path / "key"
    cert.touch()
    key.touch()
    settings.APP_ENV = "production"
    settings.HOME_HUB_SERVER_TLS_CERTFILE = str(cert)
    settings.HOME_HUB_SERVER_TLS_KEYFILE = str(key)
    context = Mock()
    context.load_cert_chain.side_effect = ValueError("fake secret")
    monkeypatch.setattr(run.ssl, "SSLContext", Mock(return_value=context))
    with pytest.raises(ValueError, match="invalid or unreadable") as error:
        run.main()
    assert "fake secret" not in str(error.value)
    server.assert_not_called()


@pytest.mark.parametrize("scheme,origin,host,extra,allowed", [
    ("https", "https://hub.example", "hub.example", {}, True),
    ("wss", "https://hub.example", "hub.example", {}, True),
    ("http", "http://192.168.1.2", "192.168.1.2", {}, False),
    ("https", "https://evil.example", "hub.example", {}, False),
    ("https", "https://hub.example", "evil.example", {}, False),
    ("https", "https://hub.example", "hub.example", {"x-forwarded-proto": "https"}, False),
    ("http", "https://hub.example", "hub.example", {}, False),
    ("ws", "https://hub.example", "hub.example", {}, False),
])
def test_owner_transport_matrix(monkeypatch, scheme, origin, host, extra, allowed):
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS",
                        "https://hub.example,http://192.168.1.2")
    conn = SimpleNamespace(headers={"origin": origin, "host": host, **extra},
                           scope={"scheme": scheme}, client=SimpleNamespace(host="192.168.1.3"))
    assert owner.valid_context(conn) is allowed


def test_https_login_sets_secure_cookie(monkeypatch):
    monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", "https://hub.example")
    monkeypatch.setattr(owner, "_verify", lambda *_: True)
    owner._attempts.clear()
    app = FastAPI()
    app.include_router(owner.router)
    with TestClient(app, base_url="https://hub.example") as client:
        response = client.post("/api/owner/session", headers={"Origin": "https://hub.example"},
                               json={"password": "fake"})
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]

@pytest.mark.parametrize("host,port,env", [
    ("127.0.0.1", 8000, "production"),
    ("", 8443, "production"),
    ("0.0.0.0", 8443, "production"),
    ("::", 8443, "production"),
    ("203.0.113.9", 8443, "production"),
    ("hub.example", 8443, "production"),
    ("127.0.0.1", 8443, "development"),
])
def test_listener_guards(startup, host, port, env):
    settings, server = startup
    settings.HOME_HUB_SERVER_TLS_CERTFILE = "cert"
    settings.HOME_HUB_SERVER_TLS_KEYFILE = "key"
    settings.HOME_HUB_SERVER_TLS_HOST = host
    settings.HOME_HUB_SERVER_TLS_PORT = port
    settings.APP_ENV = env
    with pytest.raises(ValueError):
        run.main()
    server.assert_not_called()


def test_real_dual_listener_lifecycle(tmp_path, monkeypatch):
    import asyncio
    import base64
    import hashlib
    import shutil
    import socket
    import ssl
    import subprocess
    from contextlib import asynccontextmanager

    import httpx
    import uvicorn
    import websockets
    from fastapi import WebSocket
    from fastapi.websockets import WebSocketDisconnect

    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    openssl = shutil.which("openssl")
    if openssl:
        # GitHub's Ubuntu test image has OpenSSL but does not install the
        # optional Python cryptography package. Exercise real disposable
        # HTTPS/WSS sockets without adding a production/test dependency.
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
             "-days", "1", "-subj", "/CN=localhost",
             "-addext", "subjectAltName=IP:127.0.0.1",
             "-keyout", str(key_path), "-out", str(cert_path)],
            check=True, capture_output=True,
        )
        unencrypted_key = key_path.read_bytes()
        encrypted_path = tmp_path / "encrypted.pem"
        subprocess.run(
            [openssl, "pkey", "-in", str(key_path), "-aes256",
             "-passout", "pass:synthetic-password", "-out", str(encrypted_path)],
            check=True, capture_output=True,
        )
        encrypted_key = encrypted_path.read_bytes()
    else:
        # Preserve the existing Windows/Sandbox fixture when openssl is not
        # available on PATH. Both branches create only temporary test keys.
        import datetime
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
                .sign(key, hashes.SHA256()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        unencrypted_key = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        encrypted_key = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"synthetic-password"))
        key_path.write_bytes(unencrypted_key)
    monkeypatch.setattr(run, "settings", SimpleNamespace(
        APP_ENV="production", HOME_HUB_SERVER_TLS_CERTFILE=str(cert_path),
        HOME_HUB_SERVER_TLS_KEYFILE=str(key_path), HOME_HUB_SERVER_TLS_HOST="127.0.0.1",
        HOME_HUB_SERVER_TLS_PORT=8443))
    assert isinstance(run._tls_context(), ssl.SSLContext)
    key_path.write_bytes(encrypted_key)
    with pytest.raises(ValueError, match="invalid or unreadable"):
        run._tls_context()
    key_path.write_bytes(b"malformed")
    with pytest.raises(ValueError, match="invalid or unreadable"):
        run._tls_context()
    key_path.write_bytes(unencrypted_key)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    client_tls = ssl.create_default_context(cafile=str(cert_path))
    events = []

    @asynccontextmanager
    async def lifespan(app):
        events.append("start")
        app.state.sessions = set()
        yield
        events.append("stop")

    app = FastAPI(lifespan=lifespan)
    app.include_router(owner.router)

    @app.get("/")
    async def root(request: __import__("starlette.requests", fromlist=["Request"]).Request):
        app.state.sessions.add("synthetic")
        return {"scheme": request.scope["scheme"], "state": len(app.state.sessions)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"scheme": websocket.scope["scheme"],
                                   "shared": "synthetic" in app.state.sessions,
                                   "cookie": websocket.cookies.get("session")})
        await websocket.close()

    @app.websocket("/owner-ws")
    async def owner_ws(websocket: WebSocket):
        await websocket.accept()
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                return
            await websocket.send_json({"authorized": owner.valid_session(websocket)})

    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    async def exercise():
        http_port, tls_port = free_port(), free_port()
        while tls_port == http_port:
            tls_port = free_port()
        origin = f"https://127.0.0.1:{tls_port}"
        salt = b"synthetic-16bytes"
        digest = hashlib.pbkdf2_hmac("sha256", b"fake fixture passphrase", salt, 600_000)
        verifier = "pbkdf2_sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()
        monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_PASSWORD_VERIFIER", verifier)
        monkeypatch.setattr(owner.settings, "HOME_HUB_OWNER_ALLOWED_ORIGINS", origin)
        owner._sessions.clear()
        owner._attempts.clear()
        config = uvicorn.Config(app, host="127.0.0.1", port=http_port, proxy_headers=False,
                                log_level="critical", lifespan="on")
        server = run.DualTransportServer(config, tls, "127.0.0.1", tls_port)
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started and len(server.servers) == 2:
                    break
                if task.done():
                    await task
                await asyncio.sleep(.01)
            assert len(server.servers) == 2
            async with httpx.AsyncClient(trust_env=False, verify=client_tls) as client:
                http = await client.get(f"http://127.0.0.1:{http_port}/", headers={"X-Forwarded-Proto": "https"})
                https = await client.get(f"https://127.0.0.1:{tls_port}/")
                assert http.json() == {"scheme": "http", "state": 1}
                assert https.json() == {"scheme": "https", "state": 1}
            import json
            for scheme, port, ctx, expected in [("ws", http_port, None, "ws"),
                                                 ("wss", tls_port, client_tls, "wss")]:
                async with websockets.connect(f"{scheme}://127.0.0.1:{port}/ws", ssl=ctx,
                                              additional_headers={"Cookie": "session=synthetic"},
                                              proxy=None) as connection:
                    assert json.loads(await connection.recv()) == {"scheme": expected, "shared": True,
                                                                  "cookie": "synthetic"}
            # Real HTTPS login on the extra listener must issue a Secure cookie,
            # and the same established WSS socket must deny after HTTP logout.
            async with httpx.AsyncClient(trust_env=False, verify=client_tls) as owner_client:
                login = await owner_client.post(
                    f"{origin}/api/owner/session", headers={"Origin": origin},
                    json={"password": "fake fixture passphrase"})
                assert login.status_code == 200
                assert "Secure" in login.headers["set-cookie"]
                assert "HttpOnly" in login.headers["set-cookie"]
                assert "SameSite=strict" in login.headers["set-cookie"]
                token = owner_client.cookies.get(owner.COOKIE)
                assert token
                async with websockets.connect(
                        f"wss://127.0.0.1:{tls_port}/owner-ws", ssl=client_tls,
                        origin=origin, additional_headers={"Cookie": f"{owner.COOKIE}={token}"},
                        proxy=None) as connection:
                    await connection.send("fake-fixture-command")
                    assert json.loads(await connection.recv()) == {"authorized": True}
                    logout = await owner_client.delete(
                        f"{origin}/api/owner/session", headers={"Origin": origin})
                    assert logout.status_code == 200
                    await connection.send("fake-fixture-command")
                    assert json.loads(await connection.recv()) == {"authorized": False}
                # Reauthenticate so the following negative cases use a VALID
                # owner token and test the transport boundary, not revocation.
                relogin = await owner_client.post(
                    f"{origin}/api/owner/session", headers={"Origin": origin},
                    json={"password": "fake fixture passphrase"})
                assert relogin.status_code == 200
                token = owner_client.cookies.get(owner.COOKIE)
                assert token
                # Spoofed forwarded transport headers and wrong origins must
                # deny even when the cookie points to a live owner session.
                for bad_headers, bad_origin in [
                        ({"Cookie": f"{owner.COOKIE}={token}", "X-Forwarded-Proto": "https"}, origin),
                        ({"Cookie": f"{owner.COOKIE}={token}"}, "https://evil.example")]:
                    async with websockets.connect(
                            f"wss://127.0.0.1:{tls_port}/owner-ws", ssl=client_tls,
                            origin=bad_origin, additional_headers=bad_headers,
                            proxy=None) as connection:
                        await connection.send("fake-fixture-command")
                        assert json.loads(await connection.recv()) == {"authorized": False}
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)
        assert events == ["start", "stop"]
        for port in (http_port, tls_port):
            with socket.socket() as sock:
                assert sock.connect_ex(("127.0.0.1", port)) != 0

        events.clear()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = free_port()
            config = uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False,
                                    log_level="critical", lifespan="on")
            failed = run.DualTransportServer(config, tls, "127.0.0.1", occupied.getsockname()[1])
            # Invoke startup directly to avoid SystemExit escaping an asyncio task.
            config.load()
            failed.lifespan = config.lifespan_class(config)
            with pytest.raises(SystemExit, match="could not bind"):
                await failed.startup()
            assert events == ["start", "stop"]
            with socket.socket() as sock:
                assert sock.connect_ex(("127.0.0.1", port)) != 0

    asyncio.run(asyncio.wait_for(exercise(), 15))

@pytest.mark.parametrize("host", [
    "127.0.0.1", "::1", "10.0.0.2", "172.20.2.1", "192.168.86.210", "fd00::1",
])
def test_explicit_local_tls_bind_address_allowed(host):
    """A deliberate same-LAN bind remains possible; wildcard/public is not."""
    run._validate_tls_host(host)
