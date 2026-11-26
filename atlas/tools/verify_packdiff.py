"""Run with `python -m atlas.tools.verify_packdiff` (via the sandbox wrapper).

Pack comparison and selective fill: diff shape, idempotence, conflict risk,
group-chat parity, and the friendship / receiver gates.
"""
import os
import tempfile

from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as folder:
    os.environ["ATLAS_DATA"] = folder
    from atlas.seed import app, seed

    seed()

    def client(username, password):
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"username": username, "password": password}).is_success
        return c

    alice = client("alice", "Alice123!")  # id 2
    bob = client("bob", "Bob12345!")      # id 3
    carol = client("carol", "Carol123!")  # id 4

    assert set(bob.get("/api/pack").json()["mods"]) == {"fabric-api", "sodium"}

    # Alice adds one mod and shares the snapshot.
    assert alice.post("/api/pack/action", json={"op": "add", "value": "appleskin"}).is_success
    shared = alice.post("/api/chat/3/pack")
    assert shared.is_success, shared.text
    mid = shared.json()["id"]

    diff = bob.get(f"/api/chat/2/pack/{mid}/compare")
    assert diff.is_success, diff.text
    data = diff.json()
    assert data["mine_count"] == 2 and data["theirs_count"] == 3, data
    assert [m["slug"] for m in data["only_theirs"]] == ["appleskin"], data
    assert data["only_theirs"][0]["title"] and data["only_theirs"][0]["in_library"], data
    assert data["only_mine"] == [], data
    assert sorted(data["same"]) == ["fabric-api", "sodium"], data
    assert data["version_diff"] == [], data
    assert data["risks"] == [], data

    # Gates: only the receiver, and only a friend.
    assert alice.get(f"/api/chat/2/pack/{mid}/compare").status_code in (404, 422)
    assert carol.get(f"/api/chat/2/pack/{mid}/compare").status_code == 403
    assert alice.post(f"/api/chat/2/pack/{mid}/fill", json={"slugs": ["appleskin"]}).status_code in (404, 422)
    assert carol.post(f"/api/chat/2/pack/{mid}/fill", json={"slugs": ["appleskin"]}).status_code == 403

    # An empty pick means "all" (same as the original import); an explicit
    # single pick fills exactly that one.
    filled_all = bob.post(f"/api/chat/2/pack/{mid}/fill", json={"slugs": []})
    assert filled_all.is_success and "appleskin" in filled_all.json()["mods"], filled_all.text

    # Reset Bob's draft to isolate the selective-pick assertion.
    assert bob.post("/api/pack/action", json={"op": "remove", "value": "appleskin"}).is_success
    filled = bob.post(f"/api/chat/2/pack/{mid}/fill", json={"slugs": ["appleskin"]})
    assert filled.is_success, filled.text
    assert "appleskin" in filled.json()["mods"] and filled.json()["added"], filled.text
    assert [a for a in filled.json()["added"] if "appleskin" in a.lower() or "Appleskin" in a], filled.text

    # Idempotence: the diff now shows nothing missing.
    again = bob.get(f"/api/chat/2/pack/{mid}/compare").json()
    assert again["only_theirs"] == [], again
    assert sorted(again["same"]) == ["appleskin", "fabric-api", "sodium"], again

    # Conflict risk: Alice later adds Xaero's, Bob has JourneyMap.
    assert alice.post("/api/pack/action", json={"op": "add", "value": "xaeros-minimap"}).is_success
    mid2 = alice.post("/api/chat/3/pack").json()["id"]
    assert bob.post("/api/pack/action", json={"op": "add", "value": "journeymap"}).is_success
    risky = bob.get(f"/api/chat/2/pack/{mid2}/compare").json()
    slugs = {e["a"] for e in risky["risks"]} | {e["b"] for e in risky["risks"]}
    assert "xaeros-minimap" in slugs and "journeymap" in slugs, risky
    # Filling the conflicting pick is refused by the shared merge guard.
    assert bob.post(f"/api/chat/2/pack/{mid2}/fill", json={"slugs": ["xaeros-minimap"]}).status_code == 422

    # ---------------- 群聊同款流程 ----------------
    room = alice.post("/api/rooms", json={"name": "对比小组", "members": [3]})
    assert room.is_success, room.text
    rid = room.json()["id"]
    rmid = alice.post(f"/api/rooms/{rid}/pack").json()["id"]
    rdiff = bob.get(f"/api/rooms/{rid}/pack/{rmid}/compare")
    assert rdiff.is_success, rdiff.text
    assert [m["slug"] for m in rdiff.json()["only_theirs"]] == ["xaeros-minimap"], rdiff.text
    assert carol.get(f"/api/rooms/{rid}/pack/{rmid}/compare").status_code == 403
    assert bob.post(f"/api/rooms/{rid}/pack/{rmid}/fill", json={"slugs": ["xaeros-minimap"]}).status_code == 422

    print("PASS: pack compare shape, selective fill, idempotence, conflict risk, group parity, gates.")
