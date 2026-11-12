"""Synthetic calls, clearly labelled DEMO. No real phone numbers or PBX access."""


SCENARIOS = ("team", "ddi", "internal", "queue", "priority")


def snapshot(scene):
    team = []
    members = (("223", "TB"), ("268", "PD"), ("214", "JH"), ("277", "SM"))
    for index, entry in enumerate(members):
        extension, name = entry
        member = {
            "extension": extension, "name": name,
            "led": index % 12 + 1, "state": "idle", "calls": [],
        }
        if index == 1:
            member["state"] = "busy"
            member["calls"] = [{
                "id": "demo-team-" + str(index), "state": "busy",
                "peer_name": "Example customer", "peer_number": "WITHHELD",
                "kind": "external", "priority": False, "direction": "outbound",
            }]
        if index == 2:
            member["state"] = "ringing"
        team.append(member)
    alert = None
    if scene != "team":
        alert = {
            "id": "demo-own-" + scene, "state": "ringing", "direction": "inbound",
            "peer_name": "Priority contact" if scene == "priority" else "Example caller",
            "peer_number": "201" if scene == "internal" else "WITHHELD",
            "kind": "ddi" if scene == "priority" else scene,
            "priority": scene == "priority", "ddi": "Example DDI" if scene in ("ddi", "priority") else "",
            "queue_name": "Support" if scene == "queue" else "",
            "queue_number": "800" if scene == "queue" else "",
        }
    return {
        "version": 1, "demo": True, "connected": True, "status": "DEMO",
        "age_seconds": 0, "team": team,
        "own": {"extension": "200", "name": "Mark", "calls": [alert] if alert else []},
        "alert": alert,
    }
