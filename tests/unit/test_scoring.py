import httpx

from app import config, tools

FRAUD_TX = 100541  # any existing tx id works with the mocked API


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._p


def test_score_calls_project2_api_with_its_contract(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return _Resp(
            {
                "fraud_probability": 0.97,
                "is_fraud": True,
                "threshold_used": 0.0875,
                "model_version": "baked",
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(config, "FRAUD_API_KEY", "secret-from-secret-manager")
    out = tools.score_transaction(FRAUD_TX)
    assert seen["url"].endswith("/predict")
    assert set(seen["json"]) == {"Time", "Amount", *(f"V{i}" for i in range(1, 29))}
    assert seen["headers"] == {"X-API-Key": "secret-from-secret-manager"}
    assert out["fraud_probability"] == 0.97 and out["is_fraud"] is True
    assert out["card_id"].startswith("CARD-")


def test_score_api_down_returns_explicit_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", boom)
    out = tools.score_transaction(FRAUD_TX)
    assert out["error"] == "FRAUD_API_UNAVAILABLE"
    assert "fraud_probability" not in out


def test_score_unknown_transaction():
    assert tools.score_transaction(999999)["error"] == "TRANSACTION_NOT_FOUND"
