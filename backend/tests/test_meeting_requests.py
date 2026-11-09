"""Phase 6: meeting requests -- the full lifecycle, rules, isolation, notifications and e-mails."""
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.services.email.providers import FakeProvider
from app.services.email.worker import process_due
from tests.conftest import add_active_employee, auth, register

AMMAN = timezone(timedelta(hours=3))


def at(days, hour, minute=0, tz=AMMAN):
    day = (datetime.now(tz) + timedelta(days=days)).date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).isoformat()


@pytest.fixture
def team(client):
    boss = register(client, "Acme", "boss@acme-corp.com", "Sara Boss")
    anna, anna_id = add_active_employee(client, boss, "anna@acme-corp.com", "Anna Hamdan")
    ben, ben_id = add_active_employee(client, boss, "ben@acme-corp.com", "Ben Okafor")
    boss_id = client.get("/auth/me", headers=auth(boss)).json()["user"]["id"]
    return {"boss": boss, "anna": anna, "ben": ben, "anna_id": anna_id, "ben_id": ben_id, "boss_id": boss_id}


def ask(client, tokens, times=None, **extra):
    body = {"topic": "Salary review", "note": "Before the end of the month", "proposed_times": times if times is not None else
            [at(2, 10), at(3, 11, 30), at(4, 9)], **extra}
    return client.post("/meeting-requests", json=body, headers=auth(tokens))


def notes(client, tokens):
    return client.get("/notifications", headers=auth(tokens)).json()


def events(client, tokens):
    return client.get("/calendar", headers=auth(tokens)).json()


# ---------------------------------------------------------------- lifecycles
def test_ask_propose_other_times_accept_then_cancel(client, team):
    response = ask(client, team["anna"])
    assert response.status_code == 201, response.text
    request = response.json()
    assert (request["status"], request["waiting_for"], request["requested_by_name"]) == ("pending", "manager",
                                                                                         "Anna Hamdan")
    assert len(request["proposed_times"]) == 3 and request["proposed_times"][0].endswith("+03:00")
    [note] = notes(client, team["boss"])
    assert note["kind"] == "meeting_request_new" and note["title"] == "Meeting request from Anna Hamdan"
    assert note["link"] == f"meeting-request:{request['id']}"
    assert client.get("/meeting-requests/waiting-count", headers=auth(team["boss"])).json() == {"waiting": 1}

    new_times = [at(5, 14), at(6, 15)]
    response = client.post(f"/meeting-requests/{request['id']}/reschedule",
                           json={"proposed_times": new_times, "note": "I am away that week"}, headers=auth(team["boss"]))
    assert response.status_code == 200, response.text
    moved = response.json()
    assert (moved["status"], moved["waiting_for"], moved["reply_note"]) == ("rescheduled", "employee",
                                                                            "I am away that week")
    assert moved["proposed_times"] == new_times and moved["manager_name"] == "Sara Boss"
    assert notes(client, team["anna"])[0]["kind"] == "meeting_request_rescheduled"
    assert client.get("/meeting-requests/waiting-count", headers=auth(team["anna"])).json() == {"waiting": 1}
    assert client.get("/meeting-requests/waiting-count", headers=auth(team["boss"])).json() == {"waiting": 0}

    response = client.post(f"/meeting-requests/{request['id']}/accept", json={"time": new_times[1]},
                           headers=auth(team["anna"]))
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["status"] == "accepted" and accepted["waiting_for"] is None
    assert datetime.fromisoformat(accepted["chosen_time"]) == datetime.fromisoformat(new_times[1])
    for who in ("anna", "boss"):                                   # in both calendars
        [event] = [e for e in events(client, team[who]) if e["id"] == accepted["calendar_event_id"]]
        assert event["title"] == "Meeting: Salary review"
        assert (event["start_time"], event["end_time"]) == ("15:00:00", "15:30:00")
    assert notes(client, team["boss"])[0]["kind"] == "meeting_request_accepted"

    response = client.post(f"/meeting-requests/{request['id']}/cancel", json={"reason": "Sorted it out"},
                           headers=auth(team["anna"]))
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert events(client, team["anna"]) == [] and events(client, team["boss"]) == []
    assert notes(client, team["boss"])[0]["kind"] == "meeting_request_cancelled"
    assert notes(client, team["boss"])[0]["body"] == "Sorted it out"


def test_manager_accepts_a_proposed_time_in_its_own_time_zone(client, team):
    request = ask(client, team["anna"], [at(2, 23, 45), at(3, 9)], duration_minutes=60).json()
    response = client.post(f"/meeting-requests/{request['id']}/accept", json={"time": request["proposed_times"][1],
                           "duration_minutes": 45}, headers=auth(team["boss"]))
    assert response.status_code == 200, response.text
    event = client.get(f"/calendar/{response.json()['calendar_event_id']}", headers=auth(team["anna"])).json()
    assert event["event_date"] == request["proposed_times"][1][:10]
    assert (event["start_time"], event["end_time"]) == ("09:00:00", "09:45:00")      # Amman wall-clock time
    assert [a["full_name"] for a in event["attendees"]] == ["Anna Hamdan"]
    assert notes(client, team["anna"])[0]["kind"] == "meeting_request_accepted"
    # the same instant written in UTC is the same proposed time
    other = ask(client, team["anna"], [at(5, 12)]).json()
    utc = datetime.fromisoformat(other["proposed_times"][0]).astimezone(UTC).isoformat()
    assert client.post(f"/meeting-requests/{other['id']}/accept", json={"time": utc},
                       headers=auth(team["boss"])).status_code == 200


def test_a_meeting_past_midnight_has_no_end_time(client, team):
    request = ask(client, team["anna"], [at(2, 23, 45)]).json()
    event_id = client.post(f"/meeting-requests/{request['id']}/accept", json={"time": request["proposed_times"][0]},
                           headers=auth(team["boss"])).json()["calendar_event_id"]
    event = client.get(f"/calendar/{event_id}", headers=auth(team["boss"])).json()
    assert (event["start_time"], event["end_time"]) == ("23:45:00", None)


def test_decline_is_final(client, team):
    request = ask(client, team["anna"]).json()
    assert client.post(f"/meeting-requests/{request['id']}/decline", json={"reason": ""},
                       headers=auth(team["boss"])).status_code == 422                  # a reason is required
    response = client.post(f"/meeting-requests/{request['id']}/decline", json={"reason": "Let's talk in the 1:1"},
                           headers=auth(team["boss"]))
    assert response.json()["status"] == "declined" and response.json()["decline_reason"] == "Let's talk in the 1:1"
    assert notes(client, team["anna"])[0]["body"] == "Let's talk in the 1:1"
    for path, body, who in (("accept", {"time": request["proposed_times"][0]}, "boss"),
                            ("reschedule", {"proposed_times": [at(9, 9)]}, "boss"),
                            ("decline", {"reason": "again"}, "boss"), ("cancel", {}, "anna")):
        response = client.post(f"/meeting-requests/{request['id']}/{path}", json=body, headers=auth(team[who]))
        assert response.status_code == 409, (path, response.text)


def test_manager_cancels_an_accepted_meeting(client, team):
    request = ask(client, team["anna"]).json()
    client.post(f"/meeting-requests/{request['id']}/accept", json={"time": request["proposed_times"][0]},
                headers=auth(team["boss"]))
    assert client.post(f"/meeting-requests/{request['id']}/cancel", headers=auth(team["boss"])).status_code == 200
    assert events(client, team["anna"]) == []
    assert notes(client, team["anna"])[0]["kind"] == "meeting_request_cancelled"


# ---------------------------------------------------------------- the rules
@pytest.mark.parametrize("times", [
    [],                                                       # none
    ["2026-01-01T10:00:00+03:00"],                            # in the past
    [at(1, 9), at(2, 9), at(3, 9), at(4, 9)],                 # more than three
    [at(1, 9), at(1, 9)],                                     # the same time twice
    [at(400, 9)],                                             # more than a year ahead
    ["2030-01-01T10:00:00"],                                  # no time zone
])
def test_bad_proposed_times(client, team, times):
    assert ask(client, team["anna"], times).status_code == 422


def test_who_may_do_what(client, team):
    assert ask(client, team["boss"]).status_code == 403                         # managers use the calendar
    request = ask(client, team["anna"]).json()
    rid = request["id"]
    assert client.post(f"/meeting-requests/{rid}/decline", json={"reason": "x"}, headers=auth(team["anna"])).status_code == 403
    assert client.post(f"/meeting-requests/{rid}/reschedule", json={"proposed_times": [at(9, 9)]},
                       headers=auth(team["anna"])).status_code == 403
    # the employee cannot accept their own proposal, only the manager's
    assert client.post(f"/meeting-requests/{rid}/accept", json={"time": request["proposed_times"][0]},
                       headers=auth(team["anna"])).status_code == 409
    # the manager cannot cancel an open request (they decline it)
    assert client.post(f"/meeting-requests/{rid}/cancel", headers=auth(team["boss"])).status_code == 409
    # a time that was not proposed
    assert client.post(f"/meeting-requests/{rid}/accept", json={"time": at(8, 8)},
                       headers=auth(team["boss"])).status_code == 422
    # a second answer after the first one loses
    assert client.post(f"/meeting-requests/{rid}/accept", json={"time": request["proposed_times"][0]},
                       headers=auth(team["boss"])).status_code == 200
    assert client.post(f"/meeting-requests/{rid}/accept", json={"time": request["proposed_times"][1]},
                       headers=auth(team["boss"])).status_code == 409


def test_employees_see_only_their_own_requests(client, team):
    mine = ask(client, team["anna"]).json()
    ask(client, team["ben"], topic="Ben's topic")
    assert [r["topic"] for r in client.get("/meeting-requests", headers=auth(team["anna"])).json()] == ["Salary review"]
    assert len(client.get("/meeting-requests", headers=auth(team["boss"])).json()) == 2
    assert client.get(f"/meeting-requests/{mine['id']}", headers=auth(team["ben"])).status_code == 404
    assert client.post(f"/meeting-requests/{mine['id']}/cancel", headers=auth(team["ben"])).status_code == 404
    other = register(client, "Globex", "boss@globex-corp.com", "Gil")
    assert client.get("/meeting-requests", headers=auth(other)).json() == []
    assert client.get(f"/meeting-requests/{mine['id']}", headers=auth(other)).status_code == 404
    assert client.post(f"/meeting-requests/{mine['id']}/decline", json={"reason": "x"},
                       headers=auth(other)).status_code == 404


def test_status_filters(client, team):
    first = ask(client, team["anna"]).json()
    ask(client, team["anna"], topic="Second")
    client.post(f"/meeting-requests/{first['id']}/decline", json={"reason": "no"}, headers=auth(team["boss"]))
    by = lambda s: [r["topic"] for r in client.get("/meeting-requests", params={"status": s},  # noqa: E731
                                                     headers=auth(team["boss"])).json()]
    assert by("open") == ["Second"] and by("declined") == ["Salary review"] and by("accepted") == []


def test_a_chosen_manager_is_the_only_one_told(client, team):
    second = add_active_employee(client, team["boss"], "mo@acme-corp.com", "Mo Second")
    # promote nobody: a request to an employee id is refused
    assert ask(client, team["anna"], manager_id=second[1]).status_code == 404
    response = ask(client, team["anna"], manager_id=team["boss_id"])
    assert response.status_code == 201 and response.json()["manager_name"] == "Sara Boss"
    assert len(notes(client, team["boss"])) == 1


# ---------------------------------------------------------------- notifications
def test_notifications_are_private_and_can_be_read(client, team):
    ask(client, team["anna"])
    ask(client, team["ben"], topic="Second")
    assert client.get("/notifications/unread-count", headers=auth(team["boss"])).json() == {"unread": 2}
    assert notes(client, team["anna"]) == []                            # an employee does not see the manager's
    first, second = notes(client, team["boss"])
    assert client.post(f"/notifications/{first['id']}/read", headers=auth(team["anna"])).status_code == 404
    response = client.post(f"/notifications/{first['id']}/read", headers=auth(team["boss"]))
    assert response.status_code == 200 and response.json()["read_at"]
    assert [n["id"] for n in client.get("/notifications", params={"unread": True},
                                        headers=auth(team["boss"])).json()] == [second["id"]]
    assert client.post("/notifications/read-all", headers=auth(team["boss"])).status_code == 204
    assert client.get("/notifications/unread-count", headers=auth(team["boss"])).json() == {"unread": 0}


# ---------------------------------------------------------------- e-mails
def test_every_step_is_emailed_to_the_other_side(client, team):
    request = ask(client, team["anna"]).json()
    fake = FakeProvider()
    process_due(fake)
    [new] = fake.sent
    assert new.to == "boss@acme-corp.com" and new.subject == "Meeting request: Salary review"
    assert "Anna Hamdan asked for a meeting" in new.text and "Before the end of the month" in new.text
    assert new.text.count(" · ") == 2                                  # three proposed times

    client.patch("/users/me/preferences", json={"language": "ar"}, headers=auth(team["anna"]))
    times = [at(5, 14)]
    client.post(f"/meeting-requests/{request['id']}/reschedule", json={"proposed_times": times},
                headers=auth(team["boss"]))
    process_due(fake)
    assert fake.sent[-1].to == "anna@acme-corp.com" and fake.sent[-1].subject == "مواعيد أخرى مقترحة: Salary review"
    assert "14:00" in fake.sent[-1].text

    client.post(f"/meeting-requests/{request['id']}/accept", json={"time": times[0]}, headers=auth(team["anna"]))
    process_due(fake)
    assert fake.sent[-1].to == "boss@acme-corp.com" and fake.sent[-1].subject == "Meeting accepted: Salary review"
    assert "14:00" in fake.sent[-1].text and "/meetings" in fake.sent[-1].text


def test_meeting_emails_switched_off_still_leave_the_in_app_notification(client, team):
    client.patch("/users/me/preferences", json={"email_notifications": False}, headers=auth(team["boss"]))
    ask(client, team["anna"])
    assert len(notes(client, team["boss"])) == 1
    assert process_due(FakeProvider()) == {}                           # recorded as skipped when queued
