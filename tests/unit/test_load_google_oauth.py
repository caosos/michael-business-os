"""tools/load_google_oauth.sh: runtime Google sign-in settings from protected host files; all-or-nothing; never prints a value."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("MBOS_GOOGLE_CLIENT_ID", "MBOS_GOOGLE_CLIENT_SECRET", "MBOS_GOOGLE_REDIRECT_URI", "MBOS_SESSION_SECRET")


def run(tmp_path, etc_text=None, etc_mode=0o640):
    etc = tmp_path / "etc-google-oauth.env"
    if etc_text is not None:
        etc.write_text(etc_text)
        etc.chmod(etc_mode)
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"], "DS_OAUTH_ETC_FILE": str(etc)}
    script = f'. {ROOT}/tools/load_google_oauth.sh; for n in {" ".join(NAMES)} GOOGLE_CLIENT_SECRET; do printf "%s=%s\\n" "$n" "${{!n:-}}"; done'
    p = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True)
    return dict(line.split("=", 1) for line in p.stdout.splitlines()), p.stderr


def test_owner_file_names_are_mapped_and_a_session_secret_is_generated_once(tmp_path):
    out, err = run(tmp_path, "GOOGLE_CLIENT_ID=abc.apps.googleusercontent.com\nGOOGLE_CLIENT_SECRET=s3cret-value\n")
    assert out["MBOS_GOOGLE_CLIENT_ID"] == "abc.apps.googleusercontent.com" and out["MBOS_GOOGLE_CLIENT_SECRET"] == "s3cret-value"
    assert out["MBOS_GOOGLE_REDIRECT_URI"] == "http://127.0.0.1:8766/auth/google/callback" and len(out["MBOS_SESSION_SECRET"]) >= 32
    assert out["GOOGLE_CLIENT_SECRET"] == ""                                  # the raw name is not left in the UI's environment
    assert "s3cret-value" not in err and "configured from protected host files" in err
    session = tmp_path / ".config/mbos/google-session.env"
    assert oct(session.stat().st_mode & 0o777) == "0o600"
    again, _ = run(tmp_path, "GOOGLE_CLIENT_ID=abc.apps.googleusercontent.com\nGOOGLE_CLIENT_SECRET=s3cret-value\n")
    assert again["MBOS_SESSION_SECRET"] == out["MBOS_SESSION_SECRET"]          # stable: sessions survive a restart


def test_unreadable_or_incomplete_file_leaves_sign_in_off(tmp_path):
    out, err = run(tmp_path, None)
    assert all(out[n] == "" for n in NAMES) and "not configured" in err
    out, err = run(tmp_path, "GOOGLE_CLIENT_ID=abc.apps.googleusercontent.com\n")
    assert all(out[n] == "" for n in NAMES) and "not configured" in err
