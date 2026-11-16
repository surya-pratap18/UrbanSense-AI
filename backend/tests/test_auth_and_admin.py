def _login(client, email, pw):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    return r


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"email": "Stu@Example.com", "password": "password123", "full_name": "Stu"})
    assert r.status_code == 201 and r.json()["role"] == "user"
    assert client.post("/api/auth/register", json={"email": "stu@example.com", "password": "password123"}).status_code == 409
    tok = _login(client, "stu@example.com", "password123").json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["email"] == "stu@example.com"


def test_bad_login_and_validation(client):
    assert _login(client, "nobody@x.com", "whatever1").status_code == 401
    assert client.post("/api/auth/register", json={"email": "bad", "password": "short"}).status_code == 422


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_cannot_self_register_as_admin(client):
    r = client.post("/api/auth/register", json={"email": "evil@x.com", "password": "password123", "role": "admin"})
    assert r.json()["role"] == "user"


def test_admin_endpoints_protected(client):
    client.post("/api/auth/register", json={"email": "u@x.com", "password": "password123"})
    utok = _login(client, "u@x.com", "password123").json()["access_token"]
    assert client.get("/api/admin/data-sources").status_code == 401
    assert client.get("/api/admin/data-sources", headers={"Authorization": f"Bearer {utok}"}).status_code == 403
    atok = _login(client, "admin@test.com", "adminpass1").json()["access_token"]
    h = {"Authorization": f"Bearer {atok}"}
    assert client.get("/api/admin/data-sources", headers=h).status_code == 200
    health = client.get("/api/admin/system-health", headers=h).json()["data"]
    assert health["database"] == "ok" and health["row_counts"]["users"] >= 2
    u = client.get("/api/admin/users?page=1&page_size=1", headers=h).json()
    assert u["meta"]["page_size"] == 1 and len(u["data"]) == 1


def test_data_status_never_claims_live_without_data(client):
    rows = client.get("/api/dashboard/data-status").json()["data"]
    assert {r["source_key"] for r in rows} == {"tomtom_traffic", "openaq", "open_meteo", "waste_import"}
    assert all(r["state"] == "UNAVAILABLE" for r in rows)
