from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path


PROFILES_DIR = Path(__file__).parent / ".agentbrowser" / "profiles"
DEFAULT_CHROME_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"

CACHE_DIRS = shutil.ignore_patterns(
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "DawnWebGPUCache",
    "DawnGraphiteCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    "optimization_guide_model_store",
    "Crashpad",
)

_prepared = False


def ensure_browser_profile() -> None:
    """Use a per-run scratch copy of the shared browser profile when available."""
    global _prepared
    if _prepared:
        return
    _prepared = True

    if os.environ.get("AGENT_BROWSER_PROFILE"):
        return

    shared = PROFILES_DIR / "shared"
    if not shared.exists():
        return

    run_slot = f"run_{os.getpid()}"
    dest = PROFILES_DIR / run_slot
    if not dest.exists():
        try:
            shutil.copytree(shared, dest, ignore=CACHE_DIRS)
            print(f"[Browser] Copied shared profile to profiles/{run_slot}/")
        except Exception as exc:
            print(f"[Browser] Could not copy shared profile: {exc}")
            return

    os.environ["AGENT_BROWSER_PROFILE"] = run_slot


def cleanup_run_profile() -> None:
    """Delete the scratch profile created for the current process."""
    slot = os.environ.get("AGENT_BROWSER_PROFILE", "")
    if not slot.startswith("run_"):
        return
    dest = PROFILES_DIR / slot
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
        print(f"[Browser] Cleaned up scratch profile: {slot}")


def login_session() -> None:
    """Open Chrome with the shared agent profile for manual login."""
    profile_dir = PROFILES_DIR / "shared"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "Default").mkdir(parents=True, exist_ok=True)

    chrome = _find_chrome()
    print(f"[Browser] Opening Chrome with agent profile: {profile_dir}")
    print("[Browser] Log in to any sites you need, then close Chrome completely.")
    subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "https://github.com",
        ]
    ).wait()
    print("[Browser] Chrome closed. Shared profile updated.")


def setup_profile(profile_name: str | None = None) -> None:
    """Copy an existing Chrome profile into profiles/shared for agent reuse."""
    user_data = DEFAULT_CHROME_USER_DATA
    if not user_data.exists():
        raise FileNotFoundError(f"Chrome User Data dir not found: {user_data}")

    src_profile = _find_profile(user_data, profile_name) if profile_name else _detect_main_profile(user_data)
    print(f"[Browser] Using Chrome profile: {src_profile.name}")

    dest = PROFILES_DIR / "shared"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    local_state = user_data / "Local State"
    if local_state.exists():
        _copy_local_state(local_state, dest / "Local State")

    dest_default = dest / "Default"
    shutil.copytree(src_profile, dest_default, ignore=CACHE_DIRS)

    for db_relpath in ("Network/Cookies", "Login Data", "Web Data"):
        src_db = src_profile / db_relpath
        dst_db = dest_default / db_relpath
        if src_db.exists() and dst_db.exists():
            _sqlite_backup(src_db, dst_db)

    cookies = dest_default / "Network" / "Cookies"
    if cookies.exists():
        count = sqlite3.connect(str(cookies)).execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
        print(f"[Browser] Cookies: {count} entries ({cookies.stat().st_size:,} bytes).")
    print("[Browser] Shared profile is ready.")


def _find_chrome() -> str:
    for candidate in [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Chrome not found. Set CHROME_PATH to chrome.exe.")


def _find_profile(user_data: Path, name: str | None) -> Path:
    if not name:
        return _detect_main_profile(user_data)
    path = user_data / name
    if not path.exists():
        raise FileNotFoundError(f"Chrome profile '{name}' not found in {user_data}")
    return path


def _detect_main_profile(user_data: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    for sub in user_data.iterdir():
        if not sub.is_dir():
            continue
        cookies = sub / "Network" / "Cookies"
        if cookies.exists():
            candidates.append((cookies.stat().st_size, sub))
    if not candidates:
        default = user_data / "Default"
        return default if default.exists() else next(user_data.iterdir())
    candidates.sort(reverse=True)
    best = candidates[0][1]
    print(f"[Browser] Auto-detected profile: {best.name} (cookies {candidates[0][0]:,} bytes)")
    return best


def _sqlite_backup(src: Path, dst: Path) -> None:
    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro&immutable=1", uri=True)
        dst_conn = sqlite3.connect(str(dst))
        with dst_conn:
            src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()
    except Exception as exc:
        print(f"[Browser] SQLite backup failed for {src.name}: {exc}; keeping copied DB.")


def _copy_local_state(src: Path, dest: Path) -> None:
    try:
        data = json.loads(src.read_bytes())
    except Exception:
        shutil.copy2(src, dest)
        return

    info_cache = data.get("profile", {}).get("info_cache", {})
    display_name = next(
        (value.get("name", "") for value in info_cache.values() if isinstance(value, dict) and value.get("name")),
        "",
    )
    data["profile"] = {
        "last_used": "Default",
        "last_active_profiles": ["Default"],
        "info_cache": {"Default": {"name": display_name or "Agent", "is_using_default_name": True}},
    }
    dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
