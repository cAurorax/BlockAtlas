"""Run with `python -m atlas.tools.verify_chat`.

Friend chat end to end: friendship gate, text messages, unread counters, whole-draft
sharing with merge into the receiver's draft, and co-op invites with a single decision.
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

    alice = client("alice", "Alice123!")   # id 2
    bob = client("bob", "Bob12345!")       # id 3
    carol = client("carol", "Carol123!")   # id 4

    # seeded: alice <-> bob accepted, carol -> alice pending
    assert carol.get("/api/chat/2").status_code == 403
    assert carol.post("/api/chat/2", json={"body": "hi"}).status_code == 403
    assert alice.post("/api/chat/2", json={"body": "self"}).status_code == 422

    # text message and unread accounting
    sent = alice.post("/api/chat/3", json={"body": "晚上一起试试新包？"})
    assert sent.is_success, sent.text
    assert sent.json()["kind"] == "text" and sent.json()["mine"] is True

    threads = bob.get("/api/chat/threads").json()
    mine = [t for t in threads if t["user"]["id"] == 2]
    assert mine and mine[0]["unread"] == 1, threads

    history = bob.get("/api/chat/2").json()
    assert len(history["messages"]) == 1
    assert history["messages"][0]["body"] == "晚上一起试试新包？"
    assert history["messages"][0]["mine"] is False
    assert bob.get("/api/chat/threads").json()[0]["unread"] == 0  # reading clears unread

    # share whole draft (alice adds something bob does not have yet)
    assert alice.post("/api/pack/action", json={"op": "add", "value": "appleskin"}).is_success
    shared = alice.post("/api/chat/3/pack")
    assert shared.is_success, shared.text
    payload = shared.json()["payload"]
    assert payload["mods"] and payload["mods"][0]["title"], payload
    mid = shared.json()["id"]

    before = bob.get("/api/pack").json()["mods"]
    merged = bob.post(f"/api/chat/2/pack/{mid}/import")
    assert merged.is_success, merged.text
    after = merged.json()["mods"]
    assert len(after) >= len(before)
    assert set(payload and [m["slug"] for m in payload["mods"]]) <= set(after), (payload, after)
    assert merged.json()["last"].startswith("并入")

    # merging twice is a no-op, not an error
    again = bob.post(f"/api/chat/2/pack/{mid}/import")
    assert again.is_success and again.json()["added"] == []

    # only the receiver can import, and only a pack message
    assert alice.post(f"/api/chat/2/pack/{mid}/import").status_code in (404, 422)
    assert bob.post(f"/api/chat/3/pack/{shared.json()['id']}/import").status_code in (404, 422)

    # co-op invite lifecycle
    invite = alice.post("/api/chat/3/invite", json={"address": "127.0.0.1:25565", "note": "测试服"})
    assert invite.is_success, invite.text
    assert invite.json()["status"] == "pending"
    iid = invite.json()["id"]
    assert bob.post(f"/api/chat/2/invite/{iid}/respond", json={"action": "accept"}).is_success
    assert bob.post(f"/api/chat/2/invite/{iid}/respond", json={"action": "accept"}).status_code == 409
    assert carol.post(f"/api/chat/2/invite/{iid}/respond", json={"action": "accept"}).status_code == 403

    # the invite state travels with the message history
    card = [m for m in alice.get("/api/chat/3").json()["messages"] if m["kind"] == "invite"][0]
    assert card["status"] == "accepted", card
    assert card["payload"]["address"] == "127.0.0.1:25565"

    # ---------------- 群聊 ----------------
    assert bob.post("/api/rooms", json={"name": "x", "members": [4]}).status_code == 403  # 与 carol 不是好友
    room = alice.post("/api/rooms", json={"name": "周末生存小队", "members": [3]})
    assert room.status_code == 201, room.text
    rid = room.json()["id"]

    assert carol.get(f"/api/rooms/{rid}").status_code == 403  # 非成员
    rooms = bob.get("/api/rooms").json()
    assert [r["id"] for r in rooms] == [rid] and rooms[0]["members"] and rooms[0]["unread"] == 0

    assert alice.post(f"/api/rooms/{rid}", json={"body": "周六晚上八点开服"}).is_success
    assert bob.get("/api/rooms").json()[0]["unread"] == 1
    history = bob.get(f"/api/rooms/{rid}").json()
    assert history["messages"][-1]["body"] == "周六晚上八点开服"
    assert history["messages"][-1]["mine"] is False
    assert bob.get("/api/rooms").json()[0]["unread"] == 0  # 读过就清

    shared_room = alice.post(f"/api/rooms/{rid}/pack")
    assert shared_room.is_success, shared_room.text
    rmid = shared_room.json()["id"]
    assert shared_room.json()["payload"]["mods"], shared_room.json()
    joined = bob.post(f"/api/rooms/{rid}/pack/{rmid}/import")
    assert joined.is_success and joined.json()["mods"], joined.text
    assert carol.post(f"/api/rooms/{rid}/pack/{rmid}/import").status_code == 403

    assert alice.post(f"/api/rooms/{rid}/invite", json={"address": "mc.example.com:25565"}).is_success
    assert carol.post(f"/api/rooms/{rid}/invite", json={"address": "x"}).status_code == 403
    assert bob.post(f"/api/rooms/{rid}/members", json={"uid": 4}).status_code == 403  # 非群主
    assert alice.post(f"/api/rooms/{rid}/members", json={"uid": 4}).status_code == 403  # carol 不是好友

    assert bob.post(f"/api/rooms/{rid}/leave").is_success
    assert bob.get(f"/api/rooms/{rid}").status_code == 403
    assert alice.post(f"/api/rooms/{rid}/leave").status_code == 422  # 群主不能直接退

    print("PASS: friendship gate, text + unread, draft sharing with idempotent merge, invite accept/409/403, group chat.")
