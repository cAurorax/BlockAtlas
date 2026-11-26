"""Object-oriented online mod provider abstraction and transparent catalog cache."""
from __future__ import annotations

import inspect
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from fastapi import HTTPException

SLUG_URL_RE = re.compile(r"(?:https://(?:www\.)?modrinth\.com/mod/)?([A-Za-z0-9_-]{1,80})/?")
JAR_NAME_RE = re.compile(r"[\w.+() -]+\.jar")


class ModProvider(ABC):
    """Abstract provider interface for searching and resolving mod metadata."""

    def normalize_query(self, raw: str) -> str:
        """Translate or clean user search keywords into a provider-friendly query."""
        return raw.strip()

    @abstractmethod
    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Search compatible client mods from the external repository."""

    def discover(self, category: str = "", limit: int = 12) -> tuple[list[dict], int]:
        """Browse popular compatible client mods from the external repository."""
        return [], 0

    @abstractmethod
    def resolve_release(
        self,
        slug_or_url: str,
        existing: dict[str, dict],
        auto_deps: bool = True,
    ) -> list[dict]:
        """Resolve a target mod release and optionally its missing required dependencies."""


class ModrinthProvider(ModProvider):
    """Modrinth API v2 adapter locked to Minecraft Java 1.20.1 / Fabric."""

    API_BASE = "https://api.modrinth.com/v2/"
    GAME_VERSION = "1.20.1"
    LOADER = "fabric"
    MAX_DEP_DEPTH = 4
    MAX_AUTO_DEPS = 6
    CACHE_TTL = 120.0
    ALLOWED_CATEGORIES = {"optimization", "utility", "adventure", "decoration"}

    def __init__(self):
        self._cache: dict[tuple[str, str, int, str], tuple[float, list[dict], int]] = {}

    ZH_QUERY_MAP = {
        "连锁伐木": "fallingtree",
        "配方查询": "jei",
        "食物信息": "appleskin",
        "性能优化": "sodium",
        "基础依赖": "fabric-api",
        "小地图": "minimap",
        "世界地图": "world map",
        "地图": "minimap",
        "光影": "iris shaders",
        "光影核心": "iris",
        "模组菜单": "mod menu",
        "方块信息": "jade",
        "显示血量": "jade",
        "血量显示": "jade",
        "信息提示": "jade",
        "物理优化": "lithium",
        "实体优化": "entity culling",
        "望远镜": "zoomify",
        "缩放": "zoomify",
        "动态光源": "lambdynamiclights",
        "背包整理": "inventory profiles",
        "整理背包": "inventory profiles",
        "立体皮肤": "3d skin layers",
        "皮肤": "3d skin",
        "音效": "sound physics",
        "农夫乐事": "farmers delight",
        "机械动力": "create",
        "传送石碑": "waystones",
        "传送": "waystones",
        "家具": "furniture",
        "锂": "lithium",
    }

    def normalize_query(self, raw: str) -> str:
        text = raw.strip()
        if not text:
            return ""
        lowered = text.lower()
        if lowered in self.ZH_QUERY_MAP:
            return self.ZH_QUERY_MAP[lowered]
        for zh in sorted(self.ZH_QUERY_MAP, key=len, reverse=True):
            if zh in text:
                return self.ZH_QUERY_MAP[zh]
        cleaned = re.sub(r"(模组|插件|功能|mod)", "", text, flags=re.IGNORECASE).strip()
        return cleaned or text

    def _remote(self, path: str):
        req = urllib.request.Request(
            self.API_BASE + path,
            headers={"User-Agent": "BlockAtlas-CourseDemo/2.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HTTPException(422, "Modrinth 项目不存在") from exc
            raise HTTPException(502, "Modrinth 在线服务暂不可用，请稍后重试（本地缓存仍可离线使用）") from exc
        except Exception as exc:
            raise HTTPException(502, "Modrinth 在线服务暂不可用，请稍后重试（本地缓存仍可离线使用）") from exc

    def _query_modrinth(
        self,
        query: str,
        limit: int,
        category: str = "",
        index: str = "relevance",
    ) -> tuple[list[dict], int]:
        clean_cat = category.strip().lower()
        if clean_cat not in self.ALLOWED_CATEGORIES:
            clean_cat = ""
        capped = max(1, min(int(limit), 20))
        cache_key = (query, clean_cat, capped, index)
        cached_hit = self._cache.get(cache_key)
        if cached_hit and (time.monotonic() - cached_hit[0]) < self.CACHE_TTL:
            return list(cached_hit[1]), cached_hit[2]

        facets = [
            ["project_type:mod"],
            [f"versions:{self.GAME_VERSION}"],
            [f"categories:{self.LOADER}"],
        ]
        if clean_cat:
            facets.append([f"categories:{clean_cat}"])
        params = urllib.parse.urlencode(
            {
                "query": query,
                "limit": capped,
                "index": index,
                "facets": json.dumps(facets),
            }
        )
        data = self._remote("search?" + params)
        items = []
        for hit in data.get("hits", []):
            if hit.get("client_side") == "unsupported":
                continue
            slug = hit.get("slug") or hit.get("project_id", "")
            if not slug:
                continue
            items.append(
                {
                    "slug": slug,
                    "title": hit.get("title") or slug,
                    "description": hit.get("description") or "",
                    "icon": hit.get("icon_url") or "",
                    "downloads": int(hit.get("downloads") or 0),
                    "author": hit.get("author") or "",
                    "source": f"https://modrinth.com/mod/{slug}",
                    "categories": hit.get("categories") or [],
                }
            )
        total_hits = int(data.get("total_hits") or len(items))
        self._cache[cache_key] = (time.monotonic(), list(items), total_hits)
        return items, total_hits

    def search(self, query: str, limit: int = 8, category: str = "") -> list[dict]:
        translated = self.normalize_query(query)
        if not translated:
            return []
        items, _ = self._query_modrinth(translated, limit, category=category, index="relevance")
        return items

    def discover(self, category: str = "", limit: int = 12) -> tuple[list[dict], int]:
        return self._query_modrinth("", limit, category=category, index="downloads")

    def _resolve_one(
        self,
        key: str,
        existing: dict[str, dict],
        in_stack: set[str],
        depth: int,
        batch_map: dict[str, dict],
        batch_order: list[dict],
        auto_deps: bool,
    ) -> str:
        project = self._remote("project/" + urllib.parse.quote(key, safe=""))
        slug = project["slug"]
        if slug in existing or slug in batch_map:
            return slug
        if project.get("project_type") != "mod" or project.get("client_side") == "unsupported":
            raise HTTPException(422, "仅支持客户端可用的 Minecraft Mod")
        versions_qs = urllib.parse.urlencode(
            {
                "game_versions": json.dumps([self.GAME_VERSION]),
                "loaders": json.dumps([self.LOADER]),
            }
        )
        versions = self._remote(f"project/{urllib.parse.quote(slug, safe='')}/version?" + versions_qs)
        release = next((v for v in versions if v.get("version_type") == "release"), None)
        if not release:
            raise HTTPException(422, f"{project.get('title', slug)} 没有适配 {self.GAME_VERSION} / Fabric 的正式版")

        required: list[str] = []
        conflicts: list[str] = []
        for dep in release.get("dependencies", []):
            dep_type = dep.get("dependency_type")
            if dep_type not in ("required", "incompatible"):
                continue
            ref = dep.get("project_id")
            if not ref:
                raise HTTPException(422, "此项目含未解析的依赖，请先人工核对")
            dep_project = self._remote("project/" + urllib.parse.quote(ref, safe=""))
            dep_slug = dep_project["slug"]
            if dep_type == "incompatible":
                conflicts.append(dep_slug)
                continue
            if dep_slug not in existing and dep_slug not in batch_map:
                if (
                    auto_deps
                    and depth < self.MAX_DEP_DEPTH
                    and len(batch_order) < self.MAX_AUTO_DEPS
                    and dep_slug not in in_stack
                ):
                    self._resolve_one(
                        dep_slug,
                        existing,
                        in_stack | {dep_slug},
                        depth + 1,
                        batch_map,
                        batch_order,
                        auto_deps,
                    )
                else:
                    raise HTTPException(422, "请先导入必需依赖：" + dep_slug)
            if (
                dep_slug in existing
                and dep.get("version_id")
                and dep["version_id"] != existing[dep_slug].get("id")
            ):
                raise HTTPException(422, "库内依赖版本不匹配：" + dep_slug)
            if dep_slug not in required:
                required.append(dep_slug)

        files = release.get("files") or []
        if not files:
            raise HTTPException(422, "该发布版本没有可导出的主文件")
        primary = next((f for f in files if f.get("primary")), files[0])
        if not JAR_NAME_RE.fullmatch(primary.get("filename", "")) or not primary.get("url", "").startswith(
            "https://cdn.modrinth.com/"
        ):
            raise HTTPException(422, "该发布文件暂不支持导出")

        entry = {
            "slug": slug,
            "title": project["title"],
            "description": project.get("description", ""),
            "icon": project.get("icon_url") or "",
            "version": release["version_number"],
            "id": release["id"],
            "source": f"https://modrinth.com/mod/{slug}/version/{release['id']}",
            "required": required,
            "conflicts": conflicts,
            "file": {
                "path": "mods/" + primary["filename"],
                "hashes": {
                    k: primary["hashes"][k]
                    for k in ("sha1", "sha512")
                    if k in primary.get("hashes", {})
                },
                "downloads": [primary["url"]],
                "fileSize": primary["size"],
                "env": {"client": "required", "server": project.get("server_side", "optional")},
            },
        }
        batch_map[slug] = entry
        batch_order.append(entry)
        return slug

    def resolve_release(
        self,
        slug_or_url: str,
        existing: dict[str, dict],
        auto_deps: bool = True,
    ) -> list[dict]:
        match = SLUG_URL_RE.fullmatch(slug_or_url.strip())
        if not match:
            raise HTTPException(422, "请输入 Modrinth 的 Mod 项目页链接或项目标识")
        key = match[1]
        if key in existing:
            return [existing[key]]
        batch_map: dict[str, dict] = {}
        batch_order: list[dict] = []
        resolved_slug = self._resolve_one(
            key,
            existing,
            {key},
            0,
            batch_map,
            batch_order,
            auto_deps,
        )
        if resolved_slug in existing and not batch_order:
            return [existing[resolved_slug]]
        return batch_order


class CatalogService:
    """Application service coordinating external mod providers and local SQLite cache."""

    def __init__(self, provider: ModProvider):
        self.provider = provider

    def list_cached(self, c) -> dict[str, dict]:
        return {k: json.loads(v) for k, v in c.execute("SELECT slug,data FROM resources")}

    def save_entries(self, c, entries: list[dict]) -> None:
        for item in entries:
            c.execute(
                "INSERT OR IGNORE INTO resources VALUES(?,?)",
                (item["slug"], json.dumps(item)),
            )

    def search_online(self, c, query: str = "", limit: int = 12, category: str = "") -> dict:
        cached = self.list_cached(c)
        clean_q = query.strip()
        clean_cat = category.strip().lower()
        if not clean_q:
            raw_hits, total_hits = self.provider.discover(category=clean_cat, limit=limit)
            translated = ""
            mode = "discover"
        else:
            translated = self.provider.normalize_query(clean_q)
            if clean_cat and "category" in inspect.signature(self.provider.search).parameters:
                raw_hits = self.provider.search(clean_q, limit=limit, category=clean_cat)
            else:
                raw_hits = self.provider.search(clean_q, limit=limit)
            total_hits = len(raw_hits)
            mode = "search"
        items = []
        for hit in raw_hits:
            slug = hit["slug"]
            items.append(
                {
                    **hit,
                    "cached": slug in cached,
                    "version": cached[slug]["version"] if slug in cached else "",
                }
            )
        return {
            "query": query,
            "translated": translated,
            "category": clean_cat,
            "mode": mode,
            "total_hits": total_hits,
            "provider": "modrinth",
            "items": items,
        }

    def ensure_cached(self, c, slug_or_url: str) -> tuple[dict, list[dict]]:
        cached = self.list_cached(c)
        clean = slug_or_url.strip()
        if clean in cached:
            return cached[clean], []
        entries = self.provider.resolve_release(clean, cached, auto_deps=True)
        newly = [item for item in entries if item["slug"] not in cached]
        return entries[-1], newly

    def search_and_resolve(self, c, term: str) -> tuple[dict, list[dict]]:
        cached = self.list_cached(c)
        clean = term.strip()
        lowered = clean.lower()
        for slug, item in cached.items():
            if lowered in (slug.lower(), item["title"].lower()):
                return item, []
        hits = self.provider.search(clean, limit=5)
        for hit in hits[:3]:
            slug = hit["slug"]
            if slug in cached:
                return cached[slug], []
            try:
                entries = self.provider.resolve_release(slug, cached, auto_deps=True)
            except HTTPException as exc:
                if exc.status_code == 422:
                    continue
                raise
            newly = [item for item in entries if item["slug"] not in cached]
            return entries[-1], newly
        raise HTTPException(422, f"未在 Modrinth 找到适配 1.20.1 / Fabric 的正式版 Mod：{term}")
