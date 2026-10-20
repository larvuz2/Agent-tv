from __future__ import annotations

import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_tv import FakeTV  # noqa: E402

from agent_tv.config import Config, TVEntry  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the real ~/.config/agent-tv during tests."""
    monkeypatch.setenv("AGENT_TV_HOME", str(tmp_path / "agent-tv-home"))
    for var in ("LGTV_HOST", "LGTV_CLIENT_KEY", "LGTV_MAC", "LGTV_TRANSPORT", "LGTV_PORT"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "agent-tv-home"


@pytest.fixture
async def fake_tv():
    tv = await FakeTV().start()
    yield tv
    await tv.stop()


@pytest.fixture(scope="session")
def server_tls(tmp_path_factory):
    """Self-signed cert, like the one on the TV's port 3001."""
    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    d = tmp_path_factory.mktemp("tls")
    key, cert = d / "key.pem", d / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
         "-days", "1", "-subj", "/CN=lgsmarttv.lan"],
        check=True,
        capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


@pytest.fixture
def paired_config(fake_tv):
    """A config with the fake TV registered as the default (not yet paired)."""
    cfg = Config.load()
    cfg.upsert("living-room", TVEntry(host="127.0.0.1", transport="ws", port=fake_tv.port))
    cfg.save()
    return cfg
