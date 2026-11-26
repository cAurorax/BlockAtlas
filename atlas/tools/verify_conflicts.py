"""Run with `python -m atlas.tools.verify_conflicts`.

Covers the pure graph builder (symmetrised edges, clusters, draft conflicts, risks)
and the HTTP surface against the seeded demo catalog.
"""
import os
import tempfile

from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as folder:
    os.environ["ATLAS_DATA"] = folder
    from atlas.seed import app, seed
    from atlas.conflicts import build

    seed()

    # --- pure builder -------------------------------------------------------
    catalog = {
        "a": {"title": "A", "conflicts": ["b"]},
        "b": {"title": "B"},
        "c": {"title": "C", "conflicts": ["d"]},
        "d": {"title": "D"},
        "e": {"title": "E"},
    }
    graph = build(catalog, [])
    assert graph["summary"]["mods"] == 5
    assert {tuple(sorted((e["a"], e["b"]))) for e in graph["edges"]} == {("a", "b"), ("c", "d")}
    assert len(graph["clusters"]) == 2, graph["clusters"]
    assert graph["clusters"][0]["titles"] == ["A", "B"] or graph["clusters"][0]["titles"] == ["C", "D"]

    # a one-directional declaration must still show up as one edge, and only once
    assert sum(1 for e in graph["edges"] if {e["a"], e["b"]} == {"a", "b"}) == 1

    # both sides in the draft -> draft conflict with a resolution order available
    hot = build(catalog, ["a", "b"])
    assert len(hot["draft_conflicts"]) == 1
    assert hot["risks"] == []

    # one side in the draft -> the other side is a risk
    warm = build(catalog, ["a"])
    assert [r["slug"] for r in warm["risks"]] == ["b"]
    assert warm["nodes"][0]["slug"] == "a" and warm["nodes"][0]["in_draft"] is True

    # unknown conflict targets and self references are ignored, not crashed
    clean = build({"x": {"title": "X", "conflicts": ["nope", "x"]}, "y": {"title": "Y"}}, [])
    assert clean["edges"] == [] and clean["clusters"] == []

    # --- HTTP surface -------------------------------------------------------
    def client(username, password):
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"username": username, "password": password}).is_success
        return c

    alice = client("alice", "Alice123!")
    live = alice.get("/api/conflicts")
    assert live.is_success, live.text
    graph = live.json()
    assert any({e["a"], e["b"]} == {"xaeros-minimap", "journeymap"} for e in graph["edges"]), graph["edges"]
    for node in graph["nodes"]:
        assert node["title"] and "slug" in node

    # the normal add path refuses the pair, so the graph is the safety net for the
    # explicit override below
    assert alice.post("/api/pack/action", json={"op": "add", "value": "xaeros-minimap"}).is_success
    blocked = alice.post("/api/pack/action", json={"op": "add", "value": "journeymap"})
    assert blocked.status_code == 422, blocked.text
    assert alice.post("/api/conflicts/force", json={"slug": "journeymap"}).is_success
    flagged = alice.get("/api/conflicts").json()
    assert flagged["summary"]["draft_conflicts"] == 1, flagged["summary"]

    # one click repair drops exactly one side and keeps history for undo
    fixed = alice.post("/api/conflicts/resolve", json={"keep": "xaeros-minimap", "drop": "journeymap"})
    assert fixed.is_success, fixed.text
    after = alice.get("/api/conflicts").json()
    assert after["summary"]["draft_conflicts"] == 0
    undo = alice.post("/api/pack/action", json={"op": "undo", "value": ""})
    assert undo.is_success and "journeymap" in undo.json()["mods"]

    # refusing an unrelated pair keeps the endpoint honest
    bad = alice.post("/api/conflicts/resolve", json={"keep": "sodium", "drop": "jei"})
    assert bad.status_code == 422

    print("PASS: symmetrised conflict edges, clusters, draft conflicts, risk hints, one-click repair and undo.")
