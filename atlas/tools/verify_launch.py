"""Isolated checks for the launch feature: Java discovery, memory planning,
settings persistence, command assembly, process control and safety rails."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp) / "data"
    game_root = Path(tmp) / "mvp"
    os.environ["ATLAS_DATA"] = str(data_dir)
    os.environ["ATLAS_MVP_ROOT"] = str(game_root)
    os.environ["ATLAS_ALLOW_REMOTE_LAUNCH"] = "1"

    from atlas import launcher
    from atlas.seed import app, seed

    seed()

    # --- fake installed runtime ---------------------------------------------
    minecraft = launcher.minecraft_dir()
    (minecraft / "versions" / launcher.MINECRAFT_VERSION).mkdir(parents=True)
    (minecraft / "versions" / launcher.LAUNCH_VERSION).mkdir(parents=True)
    (minecraft / "mods").mkdir(parents=True)
    for index in range(3):
        (minecraft / "mods" / f"demo-{index}.jar").write_bytes(b"x" * 1024)

    # --- pure helpers -------------------------------------------------------
    assert launcher.offline_uuid("Steve") == "5627dd98-e6be-3c21-b8a8-e92344183641"
    assert launcher.offline_uuid("Steve") == launcher.offline_uuid("Steve")
    assert launcher._major("1.8.0_401") == 8
    assert launcher._major("1.7.0_80") == 7
    assert launcher._major("17.0.9") == 17 and launcher._major("21") == 21

    plan = launcher.recommend_memory(0, {"total_mb": 16384, "available_mb": 16384, "cpus": 8})
    assert plan["suggested_mb"] == 2048, plan
    plan = launcher.recommend_memory(40, {"total_mb": 16384, "available_mb": 16384, "cpus": 8})
    assert plan["suggested_mb"] == 4352, plan
    plan = launcher.recommend_memory(200, {"total_mb": 4096, "available_mb": 4096, "cpus": 4})
    assert plan["suggested_mb"] == 2304, plan
    plan = launcher.recommend_memory(5, {"total_mb": 2048, "available_mb": 2048, "cpus": 2})
    assert plan["suggested_mb"] == 1024, plan
    assert launcher.recommend_memory(0, {})["suggested_mb"] >= launcher.MEMORY_MIN

    # --- fake Java discovery ------------------------------------------------
    fake_java = Path(tmp) / "jdk-21" / "bin" / "java.exe"
    fake_java.parent.mkdir(parents=True)
    fake_java.write_bytes(b"")
    old_java = Path(tmp) / "jdk-8" / "bin" / "java.exe"
    old_java.parent.mkdir(parents=True)
    old_java.write_bytes(b"")

    def fake_release(executable):
        if "jdk-21" in str(executable):
            return {"version": "21.0.7", "vendor": "Eclipse Adoptium", "arch": "amd64"}
        return {"version": "1.8.0_401", "vendor": "Oracle Corporation", "arch": "amd64"}

    with patch.object(launcher, "_candidate_paths", return_value=[old_java, fake_java]), patch.object(
        launcher, "_java_release", side_effect=fake_release
    ):
        rows = launcher.scan_java()
    assert [row["major"] for row in rows] == [21, 8], rows
    assert rows[0]["path"] == str(fake_java.resolve())

    # --- settings -----------------------------------------------------------
    alice = TestClient(app)
    assert alice.post(
        "/api/auth/login", json={"username": "alice", "password": "Alice123!"}
    ).status_code == 200

    payload = alice.get("/api/launch/settings").json()
    assert payload["state"]["state"] == "ready", payload["state"]
    assert payload["state"]["launchable"] is True
    assert payload["pinned"] == {
        "minecraft": "1.20.1",
        "loader": "fabric",
        "loader_version": "0.19.4",
    }
    assert payload["mods"]["installed"] == 3
    assert payload["settings"]["memory_mode"] == "auto"

    # --- java scan endpoint -------------------------------------------------
    with patch.object(launcher, "_candidate_paths", return_value=[old_java, fake_java]), patch.object(
        launcher, "_java_release", side_effect=fake_release
    ):
        scan = alice.post("/api/launch/java/scan", json={"store": True})
    assert scan.status_code == 200, scan.text
    found = scan.json()
    assert len(found["found"]) == 2
    assert len(found["items"]) == 2
    assert found["items"][0]["major"] == 21

    rec = alice.get("/api/launch/java/recommended").json()
    assert rec["path"] == str(fake_java.resolve()), rec
    assert rec["exists"] is True
    # The manual ceiling follows this machine's RAM, so derive the test value
    # from the API instead of hard-coding a number that may not fit.
    cap = int(payload["limits"]["memory_max"])
    assert cap >= launcher.MEMORY_MIN
    memory = min(6144, cap)

    saved = alice.put(
        "/api/launch/settings",
        json={
            "memory_mode": "manual",
            "memory_mb": memory,
            "width": 1920,
            "height": 1080,
            "java_path": str(fake_java.resolve()),
            "username": "Steve",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["memory_mb"] == memory
    assert alice.get("/api/launch/settings").json()["settings"]["width"] == 1920

    # invalid input is rejected
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": 512, "width": 1280, "height": 720,
              "java_path": "", "username": "Steve"},
    ).status_code == 422
    # manual memory above this machine's ceiling
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": cap + 256, "width": 1280, "height": 720,
              "java_path": "", "username": "Steve"},
    ).status_code == 422
    # any Java the player picks is accepted; the version is informational only
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": memory, "width": 1920, "height": 1080,
              "java_path": str(old_java.resolve()), "username": "Steve"},
    ).status_code == 200
    assert alice.get("/api/launch/settings").json()["settings"]["java_path"] == str(
        old_java.resolve()
    )
    # put the modern JDK back for the launch checks below
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": memory, "width": 1920, "height": 1080,
              "java_path": str(fake_java.resolve()), "username": "Steve"},
    ).status_code == 200
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": 4096, "width": 100, "height": 720,
              "java_path": "", "username": "Steve"},
    ).status_code == 422
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "weird", "memory_mb": 4096, "width": 1280, "height": 720,
              "java_path": "", "username": "Steve"},
    ).status_code == 422
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": 4096, "width": 1280, "height": 720,
              "java_path": "", "username": "bad name!"},
    ).status_code == 422
    assert alice.put(
        "/api/launch/settings",
        json={"memory_mode": "manual", "memory_mb": 4096, "width": 1280, "height": 720,
              "java_path": str(Path(tmp) / "missing-java.exe"), "username": "Steve"},
    ).status_code == 422

    # another user keeps their own defaults
    bob = TestClient(app)
    assert bob.post(
        "/api/auth/login", json={"username": "bob", "password": "Bob12345!"}
    ).status_code == 200
    assert bob.get("/api/launch/settings").json()["settings"]["memory_mb"] == 4096

    # --- command assembly ---------------------------------------------------
    captured = {}

    class FakeCommand:
        @staticmethod
        def get_minecraft_command(version, directory, options):
            captured.update(version=version, directory=directory, options=options)
            return [options.get("executablePath", "java"), "-version"]

    class FakeMcl:
        command = FakeCommand()

    with patch.object(launcher, "_mcl", return_value=FakeMcl()):
        command, effective = launcher.build_command(
            None,
            {
                "memory_mode": "manual",
                "memory_mb": 6144,
                "width": 1600,
                "height": 900,
                "username": "Steve",
            },
            None,
            str(fake_java.resolve()),
        )
    assert command == [str(fake_java.resolve()), "-version"]
    assert captured["version"] == "fabric-loader-0.19.4-1.20.1"
    assert captured["options"]["jvmArguments"] == ["-Xms512M", "-Xmx6144M"]
    assert captured["options"]["resolutionWidth"] == "1600"
    assert captured["options"]["resolutionHeight"] == "900"
    assert captured["options"]["username"] == "Steve"
    assert effective["memory_mb"] == 6144 and effective["width"] == 1600
    # The game version is pinned; it is never read from the request.
    assert effective["minecraft"] == "1.20.1" and effective["loader_version"] == "0.19.4"
    assert "window_title" not in effective

    # auto mode follows the recommendation
    with patch.object(launcher, "_mcl", return_value=FakeMcl()):
        _, effective = launcher.build_command(
            None,
            {
                "memory_mode": "auto",
                "memory_mb": 1024,
                "width": 1280,
                "height": 720,
                "username": "Steve",
            },
            None,
            str(fake_java.resolve()),
        )
    assert effective["memory_mb"] != 1024

    # --- runtime install ----------------------------------------------------
    installed = {}

    class FakeInstallApi:
        @staticmethod
        def install_minecraft_version(version, directory, callback=None):
            installed["minecraft"] = (version, directory)
            callback["setStatus"]("Download Libraries")
            callback["setProgress"](1)
            callback["setMax"](2)

    class FakeLoader:
        def install(self, minecraft_version, directory, *, loader_version=None, callback=None, java=None):
            installed["loader"] = (minecraft_version, loader_version, java)
            callback["setStatus"]("Run installer")
            return launcher.LAUNCH_VERSION

    class FakeModLoaderApi:
        @staticmethod
        def get_mod_loader(name):
            installed["loader_name"] = name
            return FakeLoader()

    class FakeMclFull:
        install = FakeInstallApi()
        mod_loader = FakeModLoaderApi()

    task = launcher.InstallTask()
    with patch.object(launcher, "_mcl", return_value=FakeMclFull()):
        snap = launcher.install_runtime(task)
    assert snap["status"] == "success", snap
    assert snap["percent"] == 100
    assert installed["minecraft"] == ("1.20.1", str(launcher.minecraft_dir()))
    assert installed["loader_name"] == "fabric"
    assert installed["loader"][0] == "1.20.1" and installed["loader"][1] == "0.19.4"

    class BoomInstallApi:
        @staticmethod
        def install_minecraft_version(version, directory, callback=None):
            raise RuntimeError("network down")

    class FakeMclBoom:
        install = BoomInstallApi()
        mod_loader = FakeModLoaderApi()

    with patch.object(launcher, "_mcl", return_value=FakeMclBoom()):
        failed = launcher.install_runtime(launcher.InstallTask())
    assert failed["status"] == "failed" and "network down" in failed["error"]

    # the install endpoints expose the task and refuse concurrent starts
    info = alice.get("/api/launch/install").json()
    assert info["task"]["status"] in ("idle", "success", "failed")
    assert info["state"]["launchable"] is True
    assert "install" in alice.get("/api/launch/status").json()
    with patch.object(launcher.INSTALL, "start", return_value=False):
        assert alice.post("/api/launch/install").status_code == 409

    # --- process control ----------------------------------------------------
    class FakeProcess:
        pid = 4242

        def __init__(self):
            self.exit_code = None

        def poll(self):
            return self.exit_code

        def terminate(self):
            self.exit_code = 0

        def wait(self, timeout=None):
            self.exit_code = 0
            return 0

        def kill(self):
            self.exit_code = -9

    fake_process = FakeProcess()
    with patch.object(launcher.subprocess, "Popen", return_value=fake_process) as popen, patch.object(
        launcher, "_mcl", return_value=FakeMcl()
    ):
        started = alice.post("/api/launch/start", json={})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["game"]["pid"] == 4242
    assert body["game"]["running"] is True
    assert body["game"]["settings"]["memory_mb"] == memory
    assert "window_title" not in body["game"]["settings"]
    command = popen.call_args[0][0]
    assert command

    state = alice.get("/api/launch/status").json()
    assert state["running"] is True and state["game"]["pid"] == 4242

    # a second launch is refused while the first is alive
    assert alice.post("/api/launch/start", json={}).status_code == 409
    # and installing is refused while a game is running
    assert alice.post("/api/launch/install").status_code == 409

    # the launcher log file exists and carries the resolved settings
    log = alice.get("/api/launch/logs?lines=50").json()
    assert log["path"].endswith(".log")
    assert f"memory={memory}MB" in log["text"]
    assert "window=1920x1080" in log["text"]
    assert log["reset"] is True
    log_file = Path(log["path"])
    assert log["offset"] == log_file.stat().st_size

    def append_log(chunk: bytes):
        with open(log_file, "ab") as handle:
            handle.write(chunk)

    # the cursor appends instead of re-reading the tail
    append_log(b"late-line\n")
    more = alice.get(f"/api/launch/logs?offset={log['offset']}").json()
    assert more["reset"] is False
    assert more["text"] == "late-line\n"
    assert more["offset"] == log_file.stat().st_size

    # polling again with the fresh cursor yields nothing new
    again = alice.get(f"/api/launch/logs?offset={more['offset']}").json()
    assert again["text"] == "" and again["offset"] == more["offset"]

    # a partial trailing line is not emitted until it is complete
    append_log(b"half")
    partial = alice.get(f"/api/launch/logs?offset={again['offset']}").json()
    assert partial["text"] == "" and partial["offset"] == again["offset"]
    append_log(b"-done\n")
    finished = alice.get(f"/api/launch/logs?offset={partial['offset']}").json()
    assert finished["text"] == "half-done\n"

    stopped = alice.post("/api/launch/stop")
    assert stopped.status_code == 200 and stopped.json()["ok"] is True
    assert fake_process.exit_code == 0
    assert alice.post("/api/launch/stop").json()["ok"] is False

    # --- missing runtime is reported, never faked --------------------------
    empty_root = Path(tmp) / "empty-mvp"
    with patch.object(launcher, "minecraft_dir", return_value=empty_root / ".minecraft"):
        state = launcher.install_state()
        assert state["state"] == "not_installed" and state["launchable"] is False

    # --- non-loopback clients cannot start a game --------------------------
    with patch.dict(os.environ, {"ATLAS_ALLOW_REMOTE_LAUNCH": "0"}):
        remote = alice.post("/api/launch/start", json={})
        assert remote.status_code == 403, remote.text

    print(
        "PASS: Java scan + storage, memory recommendation, per-user settings, "
        "input validation, pinned-version command assembly, single-game lock, "
        "stop, logs, loopback-only launch."
    )
