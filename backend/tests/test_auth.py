"""Registration, login, refresh rotation, logout, joining and validation."""
import jwt
from sqlalchemy import text

from tests.conftest import PASSWORD, add_active_employee, auth, join_with_code, login, register


def test_register_company_creates_manager_and_returns_tokens(client):
    tokens = register(client)
    me = client.get("/auth/me", headers=auth(tokens)).json()
    assert me["user"]["role"] == "manager" and me["user"]["status"] == "active"
    assert me["company"]["name"] == "Acme" and len(me["company"]["join_code"]) == 8


def test_passwords_are_stored_as_argon2_hashes(client, owner_engine):
    register(client)
    with owner_engine.connect() as connection:
        stored = connection.execute(text("SELECT password_hash FROM users")).scalar()
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_duplicate_email_is_rejected_even_in_another_company(client):
    register(client, email="same@x-corp.com")
    response = client.post("/auth/register-company", json={
        "company_name": "Other", "owner_name": "O", "email": "SAME@x-corp.com", "password": PASSWORD})
    assert response.status_code == 409


def test_input_is_validated(client):
    base = {"company_name": "A", "owner_name": "B", "email": "a@b-corp.com", "password": PASSWORD}
    assert client.post("/auth/register-company", json={**base, "password": "short"}).status_code == 422
    assert client.post("/auth/register-company", json={**base, "email": "not-an-email"}).status_code == 422
    assert client.post("/auth/register-company", json={**base, "company_name": "  "}).status_code == 422
    assert client.post("/auth/register-company", json={**base, "company_name": "x" * 121}).status_code == 422


def test_company_id_and_role_cannot_come_from_the_body(client):
    base = {"company_name": "A", "owner_name": "B", "email": "a@b-corp.com", "password": PASSWORD}
    assert client.post("/auth/register-company", json={**base, "company_id": "x"}).status_code == 422
    tokens = register(client)
    code = client.get("/company", headers=auth(tokens)).json()["join_code"]
    response = client.post("/auth/join", json={"full_name": "W", "email": "w@acme-corp.com", "password": PASSWORD,
                                               "company_code": code, "role": "manager"})
    assert response.status_code == 422


def test_login_success_and_generic_failure(client):
    register(client)
    assert login(client, "boss@acme-corp.com").status_code == 200
    wrong_password = login(client, "boss@acme-corp.com", "wrong password")
    unknown = login(client, "nobody@acme-corp.com")
    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json() == unknown.json()          # no hint whether the account exists


def test_login_is_rate_limited(client):
    register(client)
    codes = [login(client, "boss@acme-corp.com", "wrong password").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_join_with_code_waits_for_approval(client):
    manager = register(client)
    join_with_code(client, manager, "w@acme-corp.com")
    response = login(client, "w@acme-corp.com")
    assert response.status_code == 403 and "approval" in response.json()["detail"]
    employee, _ = add_active_employee(client, manager, "w2@acme-corp.com")
    assert client.get("/auth/me", headers=auth(employee)).json()["user"]["role"] == "employee"


def test_join_with_wrong_code_or_both_methods_fails(client):
    register(client)
    body = {"full_name": "W", "email": "w@acme-corp.com", "password": PASSWORD}
    assert client.post("/auth/join", json={**body, "company_code": "ZZZZ9999"}).status_code == 400
    assert client.post("/auth/join", json=body).status_code == 422
    assert client.post("/auth/join", json={**body, "company_code": "ABCD1234",
                                            "invite_token": "x" * 30}).status_code == 422


def test_invite_link_is_single_use_and_bound_to_its_email(client):
    manager = register(client)
    invite = client.post("/invites", json={"email": "invited@acme-corp.com"}, headers=auth(manager)).json()
    body = {"full_name": "I", "password": PASSWORD, "invite_token": invite["token"]}
    assert client.post("/auth/join", json={**body, "email": "other@acme-corp.com"}).status_code == 400
    assert client.post("/auth/join", json={**body, "email": "invited@acme-corp.com"}).status_code == 201
    assert client.post("/auth/join", json={**body, "email": "invited@acme-corp.com"}).status_code == 400
    assert client.get("/invites", headers=auth(manager)).json() == []    # used invites are not listed


def test_expired_invite_is_rejected(client, owner_engine):
    manager = register(client)
    invite = client.post("/invites", json={}, headers=auth(manager)).json()
    with owner_engine.begin() as connection:
        connection.execute(text("UPDATE invites SET expires_at = now() - interval '1 minute'"))
    response = client.post("/auth/join", json={"full_name": "I", "email": "i@acme-corp.com", "password": PASSWORD,
                                               "invite_token": invite["token"]})
    assert response.status_code == 400


def test_invite_token_is_stored_only_as_a_hash(client, owner_engine):
    manager = register(client)
    token = client.post("/invites", json={}, headers=auth(manager)).json()["token"]
    with owner_engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM invites")).scalar()
    assert token not in stored and len(stored) == 64


def test_refresh_rotates_and_detects_reuse(client):
    tokens = register(client)
    first = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    second_pair = first.json()
    # the old refresh token is now spent; using it again revokes the whole family
    reuse = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401
    after = client.post("/auth/refresh", json={"refresh_token": second_pair["refresh_token"]})
    assert after.status_code == 401


def test_logout_revokes_the_refresh_token(client):
    tokens = register(client)
    assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_bad_tokens_are_rejected(client):
    tokens = register(client)
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    # a refresh token is not an access token, and vice versa
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    # a token signed with another key
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    forged = jwt.encode(claims, "another-key-another-key-another-key!", algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_disabled_account_loses_access_immediately(client):
    manager = register(client)
    employee, user_id = add_active_employee(client, manager, "w@acme-corp.com")
    assert client.patch(f"/users/{user_id}/status", json={"status": "disabled"}, headers=auth(manager)).status_code == 200
    assert client.get("/auth/me", headers=auth(employee)).status_code == 401           # access token
    assert client.post("/auth/refresh", json={"refresh_token": employee["refresh_token"]}).status_code == 401
    assert login(client, "w@acme-corp.com").status_code == 403


def test_cors_allows_only_the_website_origin(client):
    allowed = client.options("/auth/login", headers={"Origin": "http://localhost:3000",
                                                     "Access-Control-Request-Method": "POST"})
    blocked = client.options("/auth/login", headers={"Origin": "https://evil.example",
                                                     "Access-Control-Request-Method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in blocked.headers


def test_signed_out_token_is_refused_without_ending_other_sessions(client):
    register(client)
    phone = login(client, "boss@acme-corp.com").json()
    laptop = login(client, "boss@acme-corp.com").json()
    client.post("/auth/logout", json={"refresh_token": phone["refresh_token"]})
    assert client.post("/auth/refresh", json={"refresh_token": phone["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": laptop["refresh_token"]}).status_code == 200


def test_the_website_may_pass_on_the_visitor_ip_only_with_the_secret(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "web_proxy_secret", SecretStr("s" * 40))
    monkeypatch.setattr(get_settings(), "login_attempts_per_ip_per_minute", 2)
    monkeypatch.setattr(get_settings(), "login_attempts_per_minute", 100)

    def attempt(n, headers):
        return client.post("/auth/login", json={"email": f"x{n}@acme-corp.com", "password": "wrong password"},
                           headers=headers).status_code

    # two visitors behind the website: each has their own limit
    for visitor in ("203.0.113.1", "203.0.113.2"):
        trusted = {"x-client-ip": visitor, "x-web-proxy-secret": "s" * 40}
        assert [attempt(i, trusted) for i in range(3)] == [401, 401, 429]
    # a made-up header without the secret is ignored: the real address counts
    fake = {"x-client-ip": "198.51.100.9", "x-web-proxy-secret": "wrong"}
    assert [attempt(i, fake) for i in range(3)] == [401, 401, 429]


# ---------------------------------------------------------------- password rules and reset (website build)
def test_new_passwords_need_ten_characters(client):
    short = client.post("/auth/register-company", json={"company_name": "Acme", "owner_name": "Boss",
                                                        "email": "boss@acme-corp.com", "password": "nine-char"})
    assert short.status_code == 422
    ok = client.post("/auth/register-company", json={"company_name": "Acme", "owner_name": "Boss",
                                                     "email": "boss@acme-corp.com", "password": "ten-chars!"})
    assert ok.status_code == 201


def _reset_link(owner_engine):
    from sqlalchemy import text as sql
    with owner_engine.connect() as c:
        row = c.execute(sql("SELECT payload, urgent, status FROM email_log WHERE template = 'password_reset' "
                            "ORDER BY id DESC LIMIT 1")).first()
    return row


def test_password_reset_flow(client, owner_engine):
    from app.services.email.providers import FakeProvider
    from app.services.email.worker import process_due

    tokens = register(client)
    answer = client.post("/auth/password/forgot", json={"email": "BOSS@acme-corp.com"})
    assert answer.status_code == 202
    unknown = client.post("/auth/password/forgot", json={"email": "nobody@acme-corp.com"})
    assert unknown.status_code == 202 and unknown.json() == answer.json()          # no account discovery
    payload, urgent, status = _reset_link(owner_engine)
    assert urgent and status == "queued" and payload["path"].startswith("/en/reset-password?token=")
    token = payload["path"].split("token=")[1]

    fake = FakeProvider()
    assert process_due(fake) == {"sent": 1}
    mail = fake.sent[0]
    assert mail.subject == "Reset your Office Assistant password"
    assert f"https://app.example.test/en/reset-password?token={token}" in mail.text
    assert "30 minutes" in mail.text and "Choose a new password" in mail.html
    assert _reset_link(owner_engine)[0] == {}                                       # the link is not kept

    assert client.post("/auth/password/reset", json={"token": token, "new_password": "short"}).status_code == 422
    assert client.post("/auth/password/reset", json={"token": token, "new_password": "a brand new secret"}).status_code == 204
    assert login(client, "boss@acme-corp.com").status_code == 401                    # the old one is gone
    assert login(client, "boss@acme-corp.com", "a brand new secret").status_code == 200
    # the link works once, and the reset signed out every session
    again = client.post("/auth/password/reset", json={"token": token, "new_password": "yet another secret"})
    assert again.status_code == 400 and "invalid or has expired" in again.json()["detail"]
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_only_the_newest_reset_link_works_and_links_expire(client, owner_engine):
    from sqlalchemy import text as sql

    register(client)
    client.post("/auth/password/forgot", json={"email": "boss@acme-corp.com"})
    first = _reset_link(owner_engine)[0]["path"].split("token=")[1]
    client.post("/auth/password/forgot", json={"email": "boss@acme-corp.com"})
    second = _reset_link(owner_engine)[0]["path"].split("token=")[1]
    assert client.post("/auth/password/reset", json={"token": first, "new_password": "a brand new secret"}).status_code == 400
    with owner_engine.begin() as c:
        c.execute(sql("UPDATE password_resets SET expires_at = now() - interval '1 minute'"))
    assert client.post("/auth/password/reset", json={"token": second, "new_password": "a brand new secret"}).status_code == 400
    assert client.post("/auth/password/reset", json={"token": "x" * 43, "new_password": "a brand new secret"}).status_code == 400


def test_arabic_reset_email_and_disabled_accounts(client, owner_engine):
    tokens = register(client)
    client.patch("/users/me/preferences", json={"language": "ar"}, headers=auth(tokens))
    client.post("/auth/password/forgot", json={"email": "boss@acme-corp.com"})
    assert _reset_link(owner_engine)[0]["path"].startswith("/ar/reset-password?token=")
    _employee_tokens, employee_id = add_active_employee(client, tokens, "anna@acme-corp.com")
    client.patch(f"/users/{employee_id}/status", json={"status": "disabled"}, headers=auth(tokens))
    before = _reset_link(owner_engine)
    client.post("/auth/password/forgot", json={"email": "anna@acme-corp.com"})
    assert _reset_link(owner_engine) == before                                      # nothing for a disabled account
