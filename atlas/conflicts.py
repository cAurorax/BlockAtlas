"""Conflict and dependency graph over the local mod catalog.

Powers the library's "冲突图" panel: which mods declare incompatibility with each
other, which clusters they form, and whether the current draft already contains a
conflicting pair (or a mod that would conflict if added).
"""
from fastapi import Depends


def build(catalog: dict, draft: list) -> dict:
    slugs = sorted(catalog)
    conflict_edges, seen = [], set()
    for slug in slugs:
        for other in catalog[slug].get("conflicts") or []:
            if other == slug or other not in catalog:
                continue
            key = tuple(sorted((slug, other)))
            if key in seen:
                continue
            seen.add(key)
            conflict_edges.append(
                {
                    "a": key[0],
                    "b": key[1],
                    "a_title": catalog[key[0]]["title"],
                    "b_title": catalog[key[1]]["title"],
                    "declared_by": slug,
                }
            )
    dep_edges = [
        {"a": slug, "b": dep}
        for slug in slugs
        for dep in (catalog[slug].get("required") or [])
        if dep in catalog and dep != slug
    ]

    # Connected components over conflict edges tell us which groups are "either-or".
    parent = {s: s for s in slugs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in conflict_edges:
        ra, rb = find(edge["a"]), find(edge["b"])
        if ra != rb:
            parent[rb] = ra
    groups = {}
    for slug in slugs:
        groups.setdefault(find(slug), []).append(slug)
    clusters = [
        {"slugs": sorted(v), "titles": [catalog[s]["title"] for s in sorted(v)]}
        for v in groups.values()
        if len(v) > 1
    ]
    clusters.sort(key=lambda c: len(c["slugs"]), reverse=True)

    in_draft = set(draft or [])
    draft_conflicts = [e for e in conflict_edges if e["a"] in in_draft and e["b"] in in_draft]
    risks = []
    for edge in conflict_edges:
        for mine, other in ((edge["a"], edge["b"]), (edge["b"], edge["a"])):
            if mine in in_draft and other not in in_draft:
                risks.append(
                    {
                        "slug": other,
                        "title": catalog[other]["title"],
                        "with": mine,
                        "with_title": catalog[mine]["title"],
                    }
                )

    nodes = []
    for slug in slugs:
        mine = [c for c in (catalog[slug].get("conflicts") or []) if c in catalog]
        reverse = [e["a"] if e["b"] == slug else e["b"] for e in conflict_edges if slug in (e["a"], e["b"])]
        effective = list(dict.fromkeys(mine + [s for s in reverse if s not in mine]))
        nodes.append(
            {
                "slug": slug,
                "title": catalog[slug]["title"],
                "icon": catalog[slug].get("icon") or "",
                "version": catalog[slug].get("version") or "",
                "source": catalog[slug].get("source") or "",
                "in_draft": slug in in_draft,
                "required": [d for d in (catalog[slug].get("required") or []) if d in catalog],
                "conflicts": effective,
                "conflicts_detail": [
                    {
                        "slug": other,
                        "title": catalog[other]["title"],
                        "declared_by_me": other in mine,
                    }
                    for other in effective
                ],
            }
        )
    return {
        "nodes": nodes,
        "edges": conflict_edges,
        "deps": dep_edges,
        "clusters": clusters,
        "draft_conflicts": draft_conflicts,
        "risks": risks,
        "summary": {
            "mods": len(slugs),
            "conflicts": len(conflict_edges),
            "clusters": len(clusters),
            "draft_conflicts": len(draft_conflicts),
            "risks": len(risks),
        },
    }


def install(app, db, current, all_mods, draft_of):
    @app.get("/api/conflicts")
    def conflicts(user=Depends(current)):
        with db.connect() as con:
            return build(all_mods(con), draft_of(con, user)["mods"])

    @app.post("/api/conflicts/force")
    def force_add(body: dict, user=Depends(current)):
        """Add a mod even though it conflicts, so the graph can show and repair it.

        The normal add path refuses conflicts; this is the explicit override a player
        reaches for when they want to see the damage before deciding.
        """
        from fastapi import HTTPException
        import json

        slug = str(body.get("slug", ""))
        with db.connect() as con:
            catalog = all_mods(con)
            if slug not in catalog:
                raise HTTPException(422, "未知的资源")
            draft = draft_of(con, user)
            if slug in draft["mods"]:
                raise HTTPException(422, catalog[slug]["title"] + " 已在草稿中")
            mods = list(draft["mods"]) + [slug]
            for key in list(mods):
                for dep in catalog[key].get("required") or []:
                    if dep in catalog and dep not in mods:
                        mods.append(dep)
            draft["history"] = (draft.get("history") or [])[-29:] + [[draft["mods"], draft["locks"]]]
            draft.update(mods=mods, last="强制加入 " + catalog[slug]["title"] + "（已声明冲突）")
            con.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)", (user["id"], json.dumps(draft)))
            return {"mods": mods, "last": draft["last"]}

    @app.post("/api/conflicts/resolve")
    def resolve(body: dict, user=Depends(current)):
        """Drop one side of a declared conflict from the draft (used by 一键修复)."""
        from fastapi import HTTPException
        from backend.security import now as stamp

        keep, drop = str(body.get("keep", "")), str(body.get("drop", ""))
        with db.connect() as con:
            catalog = all_mods(con)
            if keep not in catalog or drop not in catalog:
                raise HTTPException(422, "未知的资源")
            if drop not in (catalog[keep].get("conflicts") or []) and keep not in (
                catalog[drop].get("conflicts") or []
            ):
                raise HTTPException(422, catalog[keep]["title"] + " 与 " + catalog[drop]["title"] + " 没有声明冲突")
            draft = draft_of(con, user)
            if drop not in draft["mods"]:
                raise HTTPException(422, catalog[drop]["title"] + " 不在当前草稿中")
            for slug in draft["mods"]:
                if slug != drop and drop in (catalog[slug].get("required") or []):
                    raise HTTPException(422, catalog[slug]["title"] + " 仍需要 " + catalog[drop]["title"])
            mods = [s for s in draft["mods"] if s != drop]
            locks = [s for s in draft["locks"] if s != drop]
            draft["history"] = (draft.get("history") or [])[-29:] + [[draft["mods"], draft["locks"]]]
            draft.update(mods=mods, locks=locks, last="按冲突建议移除 " + catalog[drop]["title"], stamp=stamp())
            con.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)", (user["id"], __import__("json").dumps(draft)))
            return {"mods": mods, "last": draft["last"]}
