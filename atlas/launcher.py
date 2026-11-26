"""Game launch settings and Minecraft bootstrap.

This module is the whole "启动游戏" feature: Java discovery, memory planning,
window settings, per-user launch profiles stored in SQLite, and actually
starting/stopping the game process.

Scope note: the game version and loader are pinned to Minecraft 1.20.1 +
Fabric on purpose (the catalog in ``resources.py`` only serves that pin), so
only launch-time knobs are configurable here.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.security import now

MINECRAFT_VERSION = "1.20.1"
LOADER = "fabric"
LOADER_VERSION = "0.19.4"
LAUNCH_VERSION = f"fabric-loader-{LOADER_VERSION}-{MINECRAFT_VERSION}"

MEMORY_MIN = 1024
MEMORY_MAX = 32768
WIDTH_MIN = 640
HEIGHT_MIN = 480
SIZE_MAX = 7680
USERNAME_RE = re.compile(r"[A-Za-z0-9_]{1,16}")

# Java discovery: launcher runtimes first, then common vendor install roots.
JAVA_SEARCH_ROOTS = (
    r"C:\Program Files\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Microsoft",
    r"C:\Program Files\Amazon Corretto",
    r"C:\Program Files\Zulu",
    r"C:\Program Files\BellSoft",
    r"C:\Program Files (x86)\Java",
    r"C:\Program Files (x86)\Eclipse Adoptium",
)
JAVA_SCAN_LIMIT = 40
JAVA_RELEASE_TIMEOUT = 8


def root_dir() -> Path:
    """Shared Minecraft directory, mirroring the launcher layout."""
    base = os.environ.get("ATLAS_MVP_ROOT")
    if base:
        return Path(base).expanduser().resolve()
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "BlockAtlas" / "mvp"


def minecraft_dir() -> Path:
    return root_dir() / ".minecraft"


def _mcl():
    try:
        import minecraft_launcher_lib as mcl
    except ImportError as exc:  # optional dependency, keep the app importable
        raise HTTPException(
            503,
            "缺少 minecraft-launcher-lib，请执行 pip install -r requirements.txt 后重启服务",
        ) from exc
    return mcl


def offline_uuid(name: str) -> str:
    """Stable offline UUID, same scheme as mainstream launchers."""
    import hashlib
    import uuid

    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


# --------------------------------------------------------------------------- #
# Java discovery
# --------------------------------------------------------------------------- #


def _java_release(executable: Path) -> dict:
    """Read ``java -XshowSettings:properties -version`` for vendor/version info."""
    info = {"version": "", "vendor": "", "arch": ""}
    try:
        done = subprocess.run(
            [str(executable), "-XshowSettings:properties", "-version"],
            capture_output=True,
            timeout=JAVA_RELEASE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return info
    text = (done.stderr or b"").decode("utf-8", "replace")
    for line in text.splitlines():
        stripped = line.strip()
        for key, label in (
            ("java.version = ", "version"),
            ("java.vendor = ", "vendor"),
            ("os.arch = ", "arch"),
        ):
            if stripped.startswith(key):
                info[label] = stripped[len(key):].strip()
    return info


def _major(version: str) -> int:
    """Normalise a Java version string to its feature release (8, 17, 21, …).

    Java ≤ 8 reports ``1.8.0_401`` / ``1.7.0_80``, so the leading ``1`` is a
    scheme marker rather than the feature version.
    """
    parts = re.findall(r"\d+", version or "")
    if not parts:
        return 0
    first = int(parts[0])
    if first == 1 and len(parts) > 1:
        return int(parts[1])
    return first


def _candidate_paths() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path):
        try:
            resolved = path.resolve()
        except OSError:
            return
        key = str(resolved).lower()
        if key in seen or not resolved.is_file():
            return
        seen.add(key)
        found.append(resolved)

    # 1. Mojang runtime bundled under the shared Minecraft directory.
    for runtime_entry in sorted((minecraft_dir() / "runtime").glob("*/windows-x64/*/bin/java.exe")):
        add(runtime_entry)

    # 2. PATH and JAVA_HOME.
    for name in ("java.exe", "java"):
        hit = shutil.which(name)
        if hit:
            add(Path(hit))
    home = os.environ.get("JAVA_HOME")
    if home:
        add(Path(home) / "bin" / "java.exe")
        add(Path(home) / "bin" / "java")

    # 3. Common vendor install roots (one level deep for the jdk dir).
    for base in JAVA_SEARCH_ROOTS:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for child in sorted(base_path.iterdir()):
            if child.is_dir():
                add(child / "bin" / "java.exe")
                add(child / "jre" / "bin" / "java.exe")
                for nested in sorted(child.glob("*/bin/java.exe")):
                    add(nested)
    return found[:JAVA_SCAN_LIMIT]


def scan_java() -> list[dict]:
    """Discover local Java executables, newest major version first."""
    mojang_root = str(minecraft_dir()).lower()
    rows = []
    for executable in _candidate_paths():
        release = _java_release(executable)
        major = _major(release["version"])
        rows.append(
            {
                "path": str(executable),
                "version": release["version"],
                "vendor": release["vendor"],
                "arch": release["arch"],
                "major": major,
                "source": "mojang" if str(executable).lower().startswith(mojang_root) else "system",
            }
        )
    rows.sort(key=lambda row: (-row["major"], row["path"].lower()))
    return rows


def java_catalog(c) -> list[dict]:
    """Every Java runtime this install has ever seen, newest major first."""
    return [
        {
            "path": row["path"],
            "version": row["version"],
            "vendor": row["vendor"],
            "arch": row["arch"],
            "major": row["major"],
            "source": row["source"],
            "seen_at": row["seen_at"],
        }
        for row in c.execute(
            "SELECT path,version,vendor,arch,major,source,seen_at"
            " FROM java_runtimes ORDER BY major DESC, path"
        )
    ]


def remember_java(c, rows: list[dict]) -> None:
    for row in rows:
        c.execute(
            "INSERT INTO java_runtimes(path,version,vendor,arch,major,source,seen_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(path) DO UPDATE SET version=excluded.version,"
            " vendor=excluded.vendor,arch=excluded.arch,major=excluded.major,"
            " source=excluded.source,seen_at=excluded.seen_at",
            (
                row["path"],
                row["version"],
                row["vendor"],
                row["arch"],
                row["major"],
                row["source"],
                now(),
            ),
        )


def resolve_java(c, preferred: str = "") -> str:
    """Pick the Java executable for launch.

    Order: the player's explicit choice if still present, then the Mojang
    runtime that shipped with this Minecraft version (the combination Mojang
    itself tests), then a Java 17–21 install, then anything we know.
    """
    candidates = java_catalog(c)
    known = {row["path"]: row for row in candidates}
    if preferred:
        chosen = known.get(preferred)
        if chosen and Path(preferred).is_file():
            return preferred
    # Mojang ships java-runtime-gamma (17) for 1.20.1; it is the safest pick.
    for row in candidates:
        if row["source"] == "mojang" and 17 <= row["major"] <= 21 and Path(row["path"]).is_file():
            return row["path"]
    for row in candidates:
        if 17 <= row["major"] <= 21 and Path(row["path"]).is_file():
            return row["path"]
    for row in candidates:
        if row["major"] >= 17 and Path(row["path"]).is_file():
            return row["path"]
    for row in candidates:
        if Path(row["path"]).is_file():
            return row["path"]
    return ""


# --------------------------------------------------------------------------- #
# Memory planning
# --------------------------------------------------------------------------- #


def machine_info() -> dict:
    """Total and available physical memory in MB, plus the logical CPU count."""
    total_mb = 0
    available_mb = 0
    try:
        total_mb = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except (AttributeError, ValueError, OSError):
        total_mb = 0
    if total_mb:
        try:
            available_mb = int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024))
        except (AttributeError, ValueError, OSError):
            available_mb = 0
    if not total_mb and os.name == "nt":
        total_mb, available_mb = _windows_memory()
    return {
        "total_mb": total_mb,
        "available_mb": available_mb or total_mb,
        "cpus": os.cpu_count() or 1,
    }


def memory_ceiling(machine: dict | None = None) -> int:
    """Largest heap this machine should ever be asked for.

    The JVM reserves the whole -Xmx, so planning more than the machine can
    back leads to a failed allocation or heavy swapping.  We cap manual input
    at 70% of physical RAM (a little higher than the 60% used for the
    recommendation, because manual means the player insists).
    """
    machine = machine or machine_info()
    total = int(machine.get("total_mb") or 0)
    if not total:
        return MEMORY_MAX
    ceiling = int(total * 0.7) // 256 * 256
    return max(MEMORY_MIN, min(MEMORY_MAX, ceiling))


def _windows_memory() -> tuple[int, int]:
    """Read total/free RAM via ctypes so no extra dependency is needed."""
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0, 0
        return (
            int(status.ullTotalPhys // (1024 * 1024)),
            int(status.ullAvailPhys // (1024 * 1024)),
        )
    except Exception:  # noqa: BLE001 - memory stats are advisory only
        return 0, 0


def recommend_memory(mod_count: int, machine: dict | None = None) -> dict:
    """Suggest a heap size from mod count and the machine's own limits.

    Rule of thumb for 1.20.1 + Fabric: the base game needs ~2 GB, and every mod
    adds roughly 60 MB of loader/metadata overhead.  The result is clamped so we
    never hand the JVM more than 60% of physical RAM (the OS, drivers and the
    launcher all need headroom) and never less than the 1024 MB floor.
    """
    machine = machine or machine_info()
    mods = max(0, int(mod_count))
    wanted = 2048 + mods * 60

    total = int(machine.get("total_mb") or 0)
    reasons = [
        f"{mods} 个 Mod 按每个约 60 MB 叠加" if mods else "原版基线 2048 MB",
    ]
    if total:
        ceiling = max(MEMORY_MIN, min(MEMORY_MAX, int(total * 0.6) // 256 * 256))
        wanted = min(wanted, ceiling)
        reasons.append(f"本机 {total // 1024} GB 内存，上限取其 60%（{ceiling} MB）")
        available = int(machine.get("available_mb") or total)
        if available and wanted > available:
            usable = max(MEMORY_MIN, int(available * 0.8) // 256 * 256)
            wanted = min(wanted, usable)
            reasons.append(f"当前可用 {available // 1024} GB，按 80% 收缩到 {usable} MB")
    else:
        wanted = min(wanted, MEMORY_MAX)
        reasons.append("未能读取物理内存，按上限截断")

    suggested = max(MEMORY_MIN, min(MEMORY_MAX, wanted // 256 * 256 or MEMORY_MIN))
    return {
        "suggested_mb": suggested,
        "mod_count": mods,
        "machine": machine,
        "reasons": reasons,
    }


# --------------------------------------------------------------------------- #
# Process registry
# --------------------------------------------------------------------------- #


class GameProcess:
    """One running game, tracked so the UI can report and stop it."""

    def __init__(self, process: subprocess.Popen, log_path: Path, settings: dict):
        self.process = process
        self.log_path = log_path
        self.settings = settings
        self.started_at = now()

    @property
    def pid(self) -> int:
        return self.process.pid

    def alive(self) -> bool:
        return self.process.poll() is None

    def snapshot(self) -> dict:
        return {
            "pid": self.pid,
            "running": self.alive(),
            "started_at": self.started_at,
            "exit_code": self.process.poll(),
            "log": str(self.log_path),
            "settings": self.settings,
        }


class GameRegistry:
    """Guards the single-game-at-a-time rule."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current: GameProcess | None = None

    def get(self) -> GameProcess | None:
        with self._lock:
            current = self._current
        if current and not current.alive() and current.process.poll() is not None:
            return current  # keep the finished record so the UI can show the exit code
        return current

    def running(self) -> GameProcess | None:
        current = self.get()
        return current if current and current.alive() else None

    def start(self, process: subprocess.Popen, log_path: Path, settings: dict) -> GameProcess:
        game = GameProcess(process, log_path, settings)
        with self._lock:
            self._current = game
        return game

    def stop(self) -> dict:
        game = self.running()
        if not game:
            return {"ok": False, "reason": "当前没有正在运行的游戏"}
        try:
            game.process.terminate()
            game.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            game.process.kill()
        except OSError as exc:
            return {"ok": False, "reason": f"停止失败：{exc}"}
        with self._lock:
            self._current = game
        return {"ok": True, "pid": game.pid}


GAMES = GameRegistry()


# --------------------------------------------------------------------------- #
# Runtime installation
# --------------------------------------------------------------------------- #


class InstallTask:
    """One background install of Minecraft + the Fabric loader.

    Progress is kept in memory and read by polling.  ``version`` bumps on every
    change so the UI can tell whether it needs to repaint anything at all —
    that is what keeps the progress bar from flickering.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.status = "idle"  # idle|running|success|failed
            self.stage = ""
            self.detail = ""
            self.current = 0
            self.total = 0
            self.error = ""
            self.started_at = ""
            self.finished_at = ""
            self.version = getattr(self, "version", 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "stage": self.stage,
                "detail": self.detail,
                "current": self.current,
                "total": self.total,
                "percent": int(self.current * 100 / self.total) if self.total else 0,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "version": self.version,
            }

    def update(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)
            self.version += 1

    def start(self, job) -> bool:
        """Mark running *before* spawning the thread.

        The POST response carries this snapshot, so the worker must not be the
        one to flip the state — otherwise the reply still says ``idle`` and the
        UI never starts polling.
        """
        with self._lock:
            if self.status == "running":
                return False
            self.status = "running"
            self.stage = ""
            self.detail = "准备开始"
            self.current = 0
            self.total = 2
            self.error = ""
            self.started_at = now()
            self.finished_at = ""
            self.version += 1
        self._thread = threading.Thread(target=job, daemon=True)
        self._thread.start()
        return True


INSTALL = InstallTask()


def _make_callback(task: InstallTask):
    """Adapt minecraft-launcher-lib's callback dict to the task record.

    The library reports ``max``/``progress``/``setStatus`` per download step;
    those numbers restart for every artifact, so the bar would jump backwards.
    We only forward the human-readable status line and use our own coarse
    stage counter for the percentage.
    """

    def set_status(text: str) -> None:
        task.update(detail=str(text)[:180])

    def set_progress(value: int) -> None:
        # Keep the fine-grained number out of the bar; it is not monotonic.
        return None

    def set_max(value: int) -> None:
        return None

    return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}


def install_runtime(task: InstallTask | None = None) -> dict:
    """Download Minecraft + Fabric into the shared ``.minecraft`` directory.

    This is the piece that makes the launch feature verifiable on a fresh
    machine: without it ``install_state()`` reports ``not_installed`` and the
    launch button stays disabled.
    """
    task = task or INSTALL
    mcl = _mcl()
    target = str(minecraft_dir())
    minecraft_dir().mkdir(parents=True, exist_ok=True)

    try:
        task.update(
            status="running",
            stage="Minecraft",
            detail="准备下载游戏本体",
            current=0,
            total=2,
            error="",
            started_at=now(),
            finished_at="",
        )
        mcl.install.install_minecraft_version(
            MINECRAFT_VERSION, target, callback=_make_callback(task)
        )
        task.update(
            stage="Fabric",
            detail=f"安装 Fabric {LOADER_VERSION}",
            current=1,
        )
        loader = mcl.mod_loader.get_mod_loader(LOADER)
        # The loader installer needs a JVM; prefer the Mojang runtime we just
        # downloaded so a machine without a system Java still works.
        java = _bundled_java()
        loader.install(
            MINECRAFT_VERSION,
            target,
            loader_version=LOADER_VERSION,
            callback=_make_callback(task),
            java=java or None,
        )
        task.update(
            stage="完成",
            detail="游戏本体与加载器已安装",
            current=2,
            status="success",
            finished_at=now(),
        )
    except Exception as exc:  # noqa: BLE001 - surface the reason to the UI
        task.update(
            status="failed",
            stage="失败",
            detail="",
            error=str(exc)[:400] or exc.__class__.__name__,
            finished_at=now(),
        )
    return task.snapshot()


def _bundled_java() -> str:
    """Path to the Mojang runtime that ships with this version, if present."""
    candidates = sorted(
        (minecraft_dir() / "runtime").glob("*/windows-x64/*/bin/java.exe")
    )
    return str(candidates[0]) if candidates else ""


# --------------------------------------------------------------------------- #
# Launch settings persistence
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS java_runtimes (
 path TEXT PRIMARY KEY, version TEXT NOT NULL DEFAULT '', vendor TEXT NOT NULL DEFAULT '',
 arch TEXT NOT NULL DEFAULT '', major INTEGER NOT NULL DEFAULT 0,
 source TEXT NOT NULL DEFAULT 'system', seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS launch_settings (
 uid INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 memory_mode TEXT NOT NULL DEFAULT 'auto',
 memory_mb INTEGER NOT NULL DEFAULT 4096,
 width INTEGER NOT NULL DEFAULT 1280,
 height INTEGER NOT NULL DEFAULT 720,
 java_path TEXT NOT NULL DEFAULT '',
 username TEXT NOT NULL DEFAULT 'BlockAtlas',
 updated_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "memory_mode": "auto",
    "memory_mb": 4096,
    "width": 1280,
    "height": 720,
    "java_path": "",
    "username": "BlockAtlas",
}


def load_settings(c, uid: int) -> dict:
    row = c.execute("SELECT * FROM launch_settings WHERE uid=?", (uid,)).fetchone()
    if not row:
        return dict(DEFAULT_SETTINGS)
    data = dict(DEFAULT_SETTINGS)
    data.update({key: row[key] for key in row.keys() if key in DEFAULT_SETTINGS})
    return data


def save_settings(c, uid: int, data: dict) -> dict:
    payload = dict(DEFAULT_SETTINGS)
    payload.update({key: data[key] for key in data if key in DEFAULT_SETTINGS})
    c.execute(
        "INSERT INTO launch_settings(uid,memory_mode,memory_mb,width,height,"
        "java_path,username,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?)"
        " ON CONFLICT(uid) DO UPDATE SET memory_mode=excluded.memory_mode,"
        " memory_mb=excluded.memory_mb,width=excluded.width,height=excluded.height,"
        " java_path=excluded.java_path,"
        " username=excluded.username,"
        " updated_at=excluded.updated_at",
        (
            uid,
            payload["memory_mode"],
            payload["memory_mb"],
            payload["width"],
            payload["height"],
            payload["java_path"],
            payload["username"],
            now(),
        ),
    )
    return payload


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class LaunchSettingsInput(BaseModel):
    memory_mode: str = Field(default="auto", max_length=8)
    memory_mb: int = Field(default=4096)
    width: int = Field(default=1280)
    height: int = Field(default=720)
    java_path: str = Field(default="", max_length=500)
    username: str = Field(default="BlockAtlas", max_length=16)

    @field_validator("memory_mode")
    @classmethod
    def check_mode(cls, value: str) -> str:
        if value not in ("auto", "manual"):
            raise ValueError("内存模式只能是 auto 或 manual")
        return value

    @field_validator("memory_mb")
    @classmethod
    def check_memory(cls, value: int) -> int:
        ceiling = memory_ceiling()
        if not MEMORY_MIN <= int(value) <= ceiling:
            raise ValueError(f"内存需在 {MEMORY_MIN}-{ceiling} MB 之间（不超过本机内存的 70%）")
        return int(value)

    @field_validator("width")
    @classmethod
    def check_width(cls, value: int) -> int:
        if not WIDTH_MIN <= int(value) <= SIZE_MAX:
            raise ValueError(f"窗口宽度需在 {WIDTH_MIN}-{SIZE_MAX} 之间")
        return int(value)

    @field_validator("height")
    @classmethod
    def check_height(cls, value: int) -> int:
        if not HEIGHT_MIN <= int(value) <= SIZE_MAX:
            raise ValueError(f"窗口高度需在 {HEIGHT_MIN}-{SIZE_MAX} 之间")
        return int(value)

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        if not USERNAME_RE.fullmatch(value or ""):
            raise ValueError("离线用户名需为 1-16 位字母、数字或下划线")
        return value


class LaunchInput(BaseModel):
    memory_mb: int = Field(default=0)
    width: int = Field(default=0)
    height: int = Field(default=0)
    java_path: str = Field(default="", max_length=500)
    username: str = Field(default="", max_length=16)


class JavaScanInput(BaseModel):
    store: bool = True


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def _require_loopback(request: Request) -> None:
    """Only let the machine that runs the server start a game."""
    if os.environ.get("ATLAS_ALLOW_REMOTE_LAUNCH") == "1":
        return
    host = request.client.host if request.client else ""
    try:
        if host in ("127.0.0.1", "::1", "localhost"):
            return
        if host and socket.gethostbyname(host) in ("127.0.0.1", "::1"):
            return
    except OSError:
        pass
    raise HTTPException(403, "仅允许在本机（127.0.0.1）启动游戏")


def install_state() -> dict:
    """Whether the pinned 1.20.1 + Fabric runtime is actually installed."""
    mc_dir = minecraft_dir()
    versions = mc_dir / "versions"
    planned = {
        "minecraft": MINECRAFT_VERSION,
        "loader": LOADER,
        "loader_version": LOADER_VERSION,
        "launch_version": LAUNCH_VERSION,
        "minecraft_dir": str(mc_dir),
    }
    if not (versions / LAUNCH_VERSION).is_dir():
        if not (versions / MINECRAFT_VERSION).is_dir():
            state, detail = "not_installed", "尚未安装游戏本体"
        else:
            state, detail = "loader_missing", f"缺少 Fabric {LOADER_VERSION} 档案"
        return {
            **planned,
            "state": state,
            "launchable": False,
            "detail": detail,
        }
    return {
        **planned,
        "state": "ready",
        "launchable": True,
        "detail": "游戏本体与加载器已就绪",
    }


def mod_stats(c=None, draft=None, user=None) -> dict:
    """Count the mods a launch would actually load.

    ``installed`` is what really sits in ``.minecraft/mods``.  ``selected`` is
    the size of the player's current pack draft — the mods they are building
    towards.  Auto memory uses the larger of the two so the plan stays sane
    both before and after a pack gets installed.
    """
    mods_dir = minecraft_dir() / "mods"
    count = 0
    size = 0
    if mods_dir.is_dir():
        for path in mods_dir.iterdir():
            if path.is_file() and path.name.endswith(".jar"):
                count += 1
                try:
                    size += path.stat().st_size
                except OSError:
                    pass
    selected = 0
    if c is not None and draft is not None and user is not None:
        try:
            selected = len(draft(c, user).get("mods") or [])
        except Exception:  # noqa: BLE001 - recommendation is advisory
            selected = 0
    return {
        "installed": count,
        "installed_bytes": size,
        "selected": selected,
        "planning_count": max(count, selected),
    }


def build_command(c, settings: dict, draft, java: str, user=None) -> tuple[list[str], dict]:
    """Assemble the launch command and the effective settings behind it."""
    mcl = _mcl()
    stats = mod_stats(c, draft, user)
    if settings["memory_mode"] == "auto":
        plan = recommend_memory(stats["planning_count"])
        memory = int(plan["suggested_mb"])
    else:
        memory = int(settings["memory_mb"])
    username = settings["username"]

    options = {
        "username": username,
        "uuid": offline_uuid(username),
        "token": "",
        "gameDirectory": str(minecraft_dir()),
        "launcherName": "BlockAtlas",
        "launcherVersion": "1.0",
        "customResolution": True,
        "resolutionWidth": str(int(settings["width"])),
        "resolutionHeight": str(int(settings["height"])),
        "jvmArguments": ["-Xms512M", f"-Xmx{memory}M"],
    }
    if java:
        options["executablePath"] = java
    command = mcl.command.get_minecraft_command(
        LAUNCH_VERSION, str(minecraft_dir()), options
    )
    command = ["" if arg in ("${clientid}", "${auth_xuid}") else arg for arg in command]
    effective = {
        "memory_mb": memory,
        "memory_mode": settings["memory_mode"],
        "mod_count": stats["planning_count"],
        "width": int(settings["width"]),
        "height": int(settings["height"]),
        "java_path": java,
        "username": username,
        "launch_version": LAUNCH_VERSION,
        "minecraft": MINECRAFT_VERSION,
        "loader": LOADER,
        "loader_version": LOADER_VERSION,
    }
    return command, effective


def install(app, db, current, admin, get_post, draft):
    with db.connect() as c:
        c.executescript(SCHEMA)

    # ---- settings ---------------------------------------------------------

    @app.get("/api/launch/settings")
    def read_settings(user=Depends(current)):
        with db.connect() as c:
            stats = mod_stats(c, draft, user)
            settings = load_settings(c, user["id"])
            machine = machine_info()
            ceiling = memory_ceiling(machine)
            # A stored manual value may exceed this machine's ceiling (for
            # example after moving the data folder); surface a safe value.
            if int(settings["memory_mb"]) > ceiling:
                settings["memory_mb"] = ceiling
            return {
                "settings": settings,
                "recommendation": recommend_memory(stats["planning_count"], machine),
                "java": java_catalog(c),
                "state": install_state(),
                "mods": stats,
                "limits": {
                    "memory_min": MEMORY_MIN,
                    "memory_max": ceiling,
                    "width_min": WIDTH_MIN,
                    "height_min": HEIGHT_MIN,
                    "size_max": SIZE_MAX,
                },
                "pinned": {
                    "minecraft": MINECRAFT_VERSION,
                    "loader": LOADER,
                    "loader_version": LOADER_VERSION,
                },
            }

    @app.put("/api/launch/settings")
    def write_settings(body: LaunchSettingsInput, user=Depends(current)):
        with db.connect() as c:
            if body.java_path and not Path(body.java_path).is_file():
                raise HTTPException(422, "所选 Java 路径不存在，请重新扫描")
            saved = save_settings(
                c,
                user["id"],
                {
                    "memory_mode": body.memory_mode,
                    "memory_mb": body.memory_mb,
                    "width": body.width,
                    "height": body.height,
                    "java_path": body.java_path,
                    "username": body.username,
                },
            )
            return {"settings": saved}

    # ---- java -------------------------------------------------------------

    @app.get("/api/launch/java")
    def list_java(user=Depends(current)):
        with db.connect() as c:
            return {"items": java_catalog(c)}

    @app.post("/api/launch/java/scan")
    def scan_java_route(body: JavaScanInput, user=Depends(current)):
        rows = scan_java()
        if body.store:
            with db.connect() as c:
                remember_java(c, rows)
        with db.connect() as c:
            return {"found": rows, "items": java_catalog(c)}

    @app.get("/api/launch/java/recommended")
    def java_recommended(user=Depends(current)):
        with db.connect() as c:
            current_settings = load_settings(c, user["id"])
            path = resolve_java(c, current_settings["java_path"])
            return {
                "path": path,
                "exists": bool(path) and Path(path).is_file(),
            }

    # ---- runtime install --------------------------------------------------

    @app.get("/api/launch/install")
    def install_progress(user=Depends(current)):
        return {"task": INSTALL.snapshot(), "state": install_state()}

    @app.post("/api/launch/install", status_code=202)
    def install_start(request: Request, user=Depends(current)):
        _require_loopback(request)
        if GAMES.running():
            raise HTTPException(409, "游戏正在运行，请先停止再安装")
        if not INSTALL.start(lambda: install_runtime(INSTALL)):
            raise HTTPException(409, "已有安装任务在进行中")
        return {"task": INSTALL.snapshot(), "state": install_state()}

    # ---- memory -----------------------------------------------------------

    @app.get("/api/launch/memory")
    def memory_plan(user=Depends(current)):
        machine = machine_info()
        with db.connect() as c:
            stats = mod_stats(c, draft, user)
        return {
            "machine": machine,
            "mods": stats,
            "recommendation": recommend_memory(stats["planning_count"], machine),
            "limits": {
                "min": MEMORY_MIN,
                "max": memory_ceiling(machine),
            },
        }

    # ---- process ----------------------------------------------------------

    @app.get("/api/launch/status")
    def status(user=Depends(current)):
        game = GAMES.get()
        return {
            "running": bool(game and game.alive()),
            "game": game.snapshot() if game else None,
            "state": install_state(),
            "install": INSTALL.snapshot(),
        }

    @app.post("/api/launch/start")
    def start(request: Request, body: LaunchInput, user=Depends(current)):
        _require_loopback(request)
        if GAMES.running():
            raise HTTPException(409, "已有游戏在运行，请先停止")
        state = install_state()
        if state["state"] != "ready":
            raise HTTPException(409, state["detail"])

        with db.connect() as c:
            stored = load_settings(c, user["id"])
            java = resolve_java(c, body.java_path or stored["java_path"])
            if not java:
                raise HTTPException(
                    409,
                    "找不到可用的 Java。请在设置里扫描本机 Java，或先安装 Minecraft 游戏本体",
                )

        settings = {
            "memory_mode": stored["memory_mode"],
            "memory_mb": body.memory_mb or stored["memory_mb"],
            "width": body.width or stored["width"],
            "height": body.height or stored["height"],
            "username": body.username or stored["username"],
        }
        if body.memory_mb:
            settings["memory_mode"] = "manual"
        ceiling = memory_ceiling()
        if not MEMORY_MIN <= int(settings["memory_mb"]) <= ceiling:
            raise HTTPException(
                422,
                f"内存需在 {MEMORY_MIN}-{ceiling} MB 之间（不超过本机内存的 70%）",
            )
        if not USERNAME_RE.fullmatch(settings["username"]):
            raise HTTPException(422, "离线用户名需为 1-16 位字母、数字或下划线")

        with db.connect() as c:
            command, effective = build_command(c, settings, draft, java, user)
        executable = Path(command[0]) if command else None
        if executable and executable.is_absolute() and not executable.is_file():
            raise HTTPException(409, f"Java 不存在：{executable}")

        log_dir = minecraft_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        log_path = log_dir / f"blockatlas-launch-{stamp}.log"
        log_file = open(log_path, "ab", buffering=0)
        try:
            log_file.write(
                (
                    "=== BlockAtlas launch ===\n"
                    f"time={now()}\n"
                    f"version={LAUNCH_VERSION}\n"
                    f"username={effective['username']}\n"
                    f"memory={effective['memory_mb']}MB ({effective['memory_mode']})\n"
                    f"window={effective['width']}x{effective['height']}\n"
                    f"java={java}\n"
                    f"command={subprocess.list2cmdline(command)}\n\n"
                ).encode("utf-8")
            )
            process = subprocess.Popen(
                command,
                cwd=str(minecraft_dir()),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            log_file.close()
            raise HTTPException(409, f"启动失败：{exc}") from exc
        finally:
            log_file.close()

        game = GAMES.start(process, log_path, effective)
        return {"ok": True, "game": game.snapshot()}

    @app.post("/api/launch/stop")
    def stop(request: Request, user=Depends(current)):
        _require_loopback(request)
        return GAMES.stop()

    @app.get("/api/launch/logs")
    def logs(offset: int = -1, lines: int = 120, user=Depends(current)):
        """Tail the launcher log, either the last ``lines`` or from ``offset``.

        ``offset`` is a byte position.  Passing it back lets the log panel
        append only what is new instead of re-rendering the whole tail, which
        is what made the panel flicker.
        """
        game = GAMES.get()
        if not game:
            return {"path": "", "text": "", "offset": 0, "reset": True, "running": False}
        limit = max(1, min(int(lines), 500))
        try:
            size = game.log_path.stat().st_size
        except OSError:
            return {
                "path": str(game.log_path),
                "text": "",
                "offset": 0,
                "reset": offset < 0,
                "running": game.alive(),
            }
        if offset < 0 or offset > size:
            text = game.log_path.read_text("utf-8", errors="replace")
            tail = "\n".join(text.splitlines()[-limit:])
            return {
                "path": str(game.log_path),
                "text": tail,
                "offset": size,
                "reset": True,
                "running": game.alive(),
            }
        if offset == size:
            return {
                "path": str(game.log_path),
                "text": "",
                "offset": size,
                "reset": False,
                "running": game.alive(),
            }
        with open(game.log_path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
        # Only emit whole lines so a multi-byte character or a half-written
        # line is never decoded as garbage; retry next poll instead.
        cut = chunk.rfind(b"\n")
        if cut == -1:
            if game.alive():
                return {
                    "path": str(game.log_path),
                    "text": "",
                    "offset": offset,
                    "reset": False,
                    "running": True,
                }
            cut = len(chunk) - 1
        complete = chunk[: cut + 1]
        return {
            "path": str(game.log_path),
            "text": complete.decode("utf-8", errors="replace"),
            "offset": offset + len(complete),
            "reset": False,
            "running": game.alive(),
        }
