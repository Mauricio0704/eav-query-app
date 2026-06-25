"""HTTP-level smoke tests for the FastAPI endpoints (via TestClient)."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_questions(client):
    r = client.get("/api/questions")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    sample = data[0]
    assert {"q_id", "q_text", "q_type", "options"} <= sample.keys()


def test_attributes(client):
    r = client.get("/api/attributes")
    assert r.status_code == 200
    names = {a["attribute"] for a in r.json()}
    assert "sexo" in names


def test_cities(client):
    r = client.get("/api/cities")
    assert r.status_code == 200
    data = r.json()
    assert all("city_id" in c and "name" in c for c in data)
    assert any(c["name"] == "Monterrey" for c in data)


def test_recodes(client):
    r = client.get("/api/recodes")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_presets(client):
    r = client.get("/api/presets")
    assert r.status_code == 200
    assert len(r.json()) > 0


def test_query_endpoint(client, categorical_qid):
    r = client.post("/api/query", json={"question_id": categorical_qid})
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "flat"
    assert body["rows"]


def test_query_csv_endpoint(client, categorical_qid):
    r = client.post("/api/query/csv", json={"question_id": categorical_qid})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    assert len(r.text.splitlines()) > 1  # header + at least one data row


def test_query_unknown_question_returns_404(client):
    r = client.post("/api/query", json={"question_id": "__does_not_exist__"})
    assert r.status_code == 404
