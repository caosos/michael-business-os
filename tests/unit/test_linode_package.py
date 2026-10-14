"""deploy/linode: the public-site package stays pinned, hash-locked, isolated and loopback-only."""
import re
import subprocess
from pathlib import Path

D = Path(__file__).resolve().parents[2] / "deploy" / "linode"


def env(path):
    return dict(re.match(r"([A-Z_0-9]+)=(\S+)", l).groups() for l in path.read_text().splitlines() if re.match(r"[A-Z_0-9]+=", l))


def test_components_are_exact_commits_present_in_the_repo():
    c = env(D / "components.env")
    for k in ("UI_SHA", "MBOS_SHA", "DISCOVERY_SHA", "ECONOMICS_SHA"):
        assert re.fullmatch(r"[0-9a-f]{40}", c[k]), k
        subprocess.run(["git", "cat-file", "-e", c[k] + "^{commit}"], cwd=D, check=True)
    assert c["PORT"] == "8765"


def test_every_locked_package_has_an_exact_version_and_hash():
    for f in ("requirements.lock", "build-requirements.lock"):
        lines = [l for l in (D / f).read_text().splitlines() if l and not l.startswith("#")]
        assert lines and all(re.fullmatch(r"[a-z0-9-]+==[\w.]+ --hash=sha256:[0-9a-f]{64}", l) for l in lines), f


def test_nginx_only_names_dealsniffers_and_proxies_loopback_with_a_fixed_host():
    for f in ("dealsniffers.com.acme.conf", "dealsniffers.com.conf"):
        t = (D / "nginx" / f).read_text()
        assert "DealSniffer-managed" in t and "default_server" not in t
        assert set(re.findall(r"server_name ([^;]+);", t)) <= {"dealsniffers.com www.dealsniffers.com", "www.dealsniffers.com", "dealsniffers.com"}
    t = (D / "nginx" / "dealsniffers.com.conf").read_text()
    assert "proxy_pass http://127.0.0.1:8765;" in t and "proxy_set_header Host dealsniffers.com;" in t and "$http_host" not in t


def test_service_is_unprivileged_hardened_and_public_only():
    u = (D / "dealsniffer.service").read_text()
    for need in ("User=dealsniffer", "NoNewPrivileges=yes", "ProtectSystem=strict", "ReadWritePaths=/var/lib/dealsniffer", "CapabilityBoundingSet=\n"):
        assert need in u, need
    e = (D / "install.sh").read_text()
    assert "MBOS_PUBLIC_DEPLOYMENT=1" in e and "MBOS_GOOGLE_REDIRECT_URI=https://dealsniffers.com/auth/google/callback" in e
    assert "--require-hashes" in e and "--no-build-isolation" in e and "BRIGHTDATA" not in e
