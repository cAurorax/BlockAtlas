"""Isolated verification for OOP ModProvider, online search, auto-dependencies, and transparent cache."""
import io
import json
import os
import tempfile
import zipfile
from unittest.mock import patch
from fastapi.testclient import TestClient


def _entry(slug: str, title: str, required: list[str] | None = None):
    return {
        "slug": slug,
        "title": title,
        "description": f"{title} test mod",
        "icon": "",
        "version": f"1.20.1-{slug}",
        "id": f"ver-{slug}",
        "source": f"https://modrinth.com/mod/{slug}/version/ver-{slug}",
        "required": required or [],
        "conflicts": [],
        "file": {
            "path": f"mods/{slug}-1.20.1.jar",
            "hashes": {"sha1": f"sha1-{slug}", "sha512": f"sha512-{slug}"},
            "downloads": [f"https://cdn.modrinth.com/data/{slug}/mods/{slug}.jar"],
            "fileSize": 12345,
            "env": {"client": "required", "server": "optional"},
        },
    }


with tempfile.TemporaryDirectory() as tmp:
    os.environ["ATLAS_DATA"] = tmp
    from atlas.providers import CatalogService, ModProvider, ModrinthProvider
    from atlas.seed import app, seed
    from atlas import ai_settings

    seed()

    # 1. Keyword normalization tests on real ModrinthProvider
    real_provider = ModrinthProvider()
    assert real_provider.normalize_query("小地图") == "minimap"
    assert real_provider.normalize_query("光影") == "iris shaders"
    assert real_provider.normalize_query("实体优化") == "entity culling"

    class FakeProvider(ModProvider):
        def __init__(self):
            self.search_calls = []

        def normalize_query(self, raw: str) -> str:
            return real_provider.normalize_query(raw)

        def search(self, query: str, limit: int = 8) -> list[dict]:
            q = self.normalize_query(query).lower()
            self.search_calls.append(q)
            if "minimap" in q:
                return [
                    {
                        "slug": "demo-minimap",
                        "title": "Demo Minimap",
                        "description": "Minimap overlay",
                        "icon": "",
                        "downloads": 5000000,
                        "author": "tester",
                        "source": "https://modrinth.com/mod/demo-minimap",
                        "categories": ["fabric", "utility"],
                    }
                ]
            if "shader" in q or "iris" in q:
                return [
                    {
                        "slug": "demo-iris",
                        "title": "Demo Iris Shaders",
                        "description": "Shader loader",
                        "icon": "",
                        "downloads": 8000000,
                        "author": "tester",
                        "source": "https://modrinth.com/mod/demo-iris",
                        "categories": ["fabric", "optimization"],
                    }
                ]
            return []

        def resolve_release(self, slug_or_url: str, existing: dict[str, dict], auto_deps: bool = True) -> list[dict]:
            key = slug_or_url.strip().rstrip("/").split("/")[-1]
            if key == "demo-minimap":
                entries = []
                if "demo-core-lib" not in existing:
                    entries.append(_entry("demo-core-lib", "Demo Core Lib"))
                if "demo-minimap" not in existing:
                    entries.append(_entry("demo-minimap", "Demo Minimap", required=["demo-core-lib", "fabric-api"]))
                return entries or [existing["demo-minimap"]]
            if key == "demo-iris":
                if "demo-iris" in existing:
                    return [existing["demo-iris"]]
                return [_entry("demo-iris", "Demo Iris Shaders", required=["sodium"])]
            raise AssertionError(f"Unexpected slug resolution: {slug_or_url}")

    fake = FakeProvider()
    app.state.catalog_service = CatalogService(fake)

    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "alice", "password": "Alice123!"}).is_success

    # 2. Online search endpoint
    r = client.get("/api/library/search", params={"q": "小地图"})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["translated"] == "minimap"
    assert payload["items"][0]["slug"] == "demo-minimap"
    assert payload["items"][0]["cached"] is False

    # 3. Quick-add with recursive auto-dependency caching & draft addition
    qa = client.post("/api/library/quick-add", json={"slug": "demo-minimap"})
    assert qa.status_code == 200, qa.text
    qa_data = qa.json()
    assert "demo-minimap" in qa_data["mods"] and "demo-core-lib" in qa_data["mods"]
    assert qa_data["auto_deps"] == ["Demo Core Lib"]

    # Confirm transparent cache now marks demo-minimap as cached
    r2 = client.get("/api/library/search", params={"q": "小地图"})
    assert r2.json()["items"][0]["cached"] is True

    # 4. Offline chat fallback triggers search_add for unknown mods without breaking local aliases
    search_count_before = len(fake.search_calls)
    local_chat = client.post("/api/pack/action", json={"op": "chat", "value": "加上配方查询"})
    assert local_chat.status_code == 200, local_chat.text
    assert "jei" in local_chat.json()["mods"]
    assert len(fake.search_calls) == search_count_before

    # Undo jei, then test offline chat search_add with demo-iris via another user
    bob = TestClient(app)
    assert bob.post("/api/auth/login", json={"username": "bob", "password": "Bob12345!"}).is_success
    chat_online = bob.post("/api/pack/action", json={"op": "chat", "value": "加上光影"})
    assert chat_online.status_code == 200, chat_online.text
    assert "demo-iris" in chat_online.json()["mods"]
    assert "联网匹配并加入 Demo Iris Shaders" in chat_online.json()["last"]

    # 5. Online LLM mode returning search_add op
    def mock_chat_response(req, timeout):
        return io.BytesIO(
            json.dumps({"choices": [{"message": {"content": json.dumps({"ops": [["search_add", "minimap"]]})}}]}).encode()
        )

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fixture", "DEEPSEEK_MODEL": "deepseek-chat"}), patch.object(
        ai_settings.urllib.request.OpenerDirector, "open", side_effect=mock_chat_response
    ):
        llm_chat = bob.post("/api/pack/action", json={"op": "chat", "value": "帮我加个能看地图的插件"})
        assert llm_chat.status_code == 200, llm_chat.text
        assert "demo-minimap" in llm_chat.json()["mods"]
        assert "demo-core-lib" in llm_chat.json()["mods"]

    # 6. Export .mrpack contains online-resolved mod & auto-resolved dependency
    exp = bob.post("/api/pack/export")
    assert exp.status_code == 200, exp.text
    dl = bob.get(exp.json()["url"])
    assert dl.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl.content)) as z:
        manifest = json.loads(z.read("modrinth.index.json"))
        paths = {f["path"] for f in manifest["files"]}
        assert "mods/demo-iris-1.20.1.jar" in paths
        assert "mods/demo-minimap-1.20.1.jar" in paths
        assert "mods/demo-core-lib-1.20.1.jar" in paths

    print("PASS: OOP ModProvider, Chinese query mapping, online search, auto-dependency resolution, chat search_add (offline+LLM), and .mrpack export.")
