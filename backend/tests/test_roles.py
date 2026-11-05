"""What employees and managers may do."""
from tests.conftest import add_active_employee, auth, register


def test_employee_cannot_use_manager_endpoints(client):
    manager = register(client)
    employee, _ = add_active_employee(client, manager, "w@acme-corp.com")
    headers = auth(employee)
    assert client.get("/users", headers=headers).status_code == 403
    assert client.post("/invites", json={}, headers=headers).status_code == 403
    assert client.get("/invites", headers=headers).status_code == 403
    assert client.get("/company", headers=headers).status_code == 403
    assert client.post("/company/join-code", headers=headers).status_code == 403


def test_employee_sees_only_themselves(client):
    manager = register(client)
    employee, own_id = add_active_employee(client, manager, "w@acme-corp.com")
    _, other_id = add_active_employee(client, manager, "v@acme-corp.com")
    assert client.get(f"/users/{own_id}", headers=auth(employee)).status_code == 200
    assert client.get(f"/users/{other_id}", headers=auth(employee)).status_code == 404
    assert client.post(f"/users/{other_id}/approve", headers=auth(employee)).status_code == 403


def test_employee_does_not_receive_the_join_code(client):
    manager = register(client)
    employee, _ = add_active_employee(client, manager, "w@acme-corp.com")
    assert client.get("/auth/me", headers=auth(employee)).json()["company"]["join_code"] is None
    assert client.get("/auth/me", headers=auth(manager)).json()["company"]["join_code"]


def test_manager_approves_disables_and_reenables(client):
    manager = register(client)
    _, user_id = add_active_employee(client, manager, "w@acme-corp.com")
    headers = auth(manager)
    assert client.post(f"/users/{user_id}/approve", headers=headers).status_code == 409   # already active
    assert client.patch(f"/users/{user_id}/status", json={"status": "disabled"}, headers=headers).json()["status"] == "disabled"
    assert client.patch(f"/users/{user_id}/status", json={"status": "active"}, headers=headers).json()["status"] == "active"
    assert client.patch(f"/users/{user_id}/status", json={"status": "pending"}, headers=headers).status_code == 422


def test_manager_cannot_disable_themselves(client):
    manager = register(client)
    me = client.get("/auth/me", headers=auth(manager)).json()["user"]["id"]
    assert client.patch(f"/users/{me}/status", json={"status": "disabled"}, headers=auth(manager)).status_code == 409


def test_rotating_the_join_code_invalidates_the_old_one(client):
    manager = register(client)
    old = client.get("/company", headers=auth(manager)).json()["join_code"]
    new = client.post("/company/join-code", headers=auth(manager)).json()["join_code"]
    assert new != old
    body = {"full_name": "W", "email": "w@acme-corp.com", "password": "correct horse battery"}
    assert client.post("/auth/join", json={**body, "company_code": old}).status_code == 400
    assert client.post("/auth/join", json={**body, "company_code": new}).status_code == 201
