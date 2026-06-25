"""Tests for the pure (non-LLM) helpers in chat.py.

These never call Gemini — they exercise the argument normalization, the
JSON-safety coercion (the Decimal→float fix that prevented a 502), and the
tool-call executor that wraps run_query.
"""

import json
from decimal import Decimal

import pytest

import chat


def test_norm_value_scalar_and_list():
    assert chat._norm_value(5) == 5
    assert chat._norm_value([1, "2", 3]) == [1, 2, 3]


def test_norm_city_value_accepts_numeric():
    assert chat._norm_city_value([39, "6"]) == [39, 6]


def test_norm_city_value_rejects_zone_names():
    with pytest.raises(ValueError):
        chat._norm_city_value(["AMM"])


def test_jsonable_coerces_decimals():
    out = chat._jsonable({"a": Decimal("5.5"), "b": [Decimal("1"), {"c": Decimal("2.25")}]})
    assert out == {"a": 5.5, "b": [1.0, {"c": 2.25}]}
    json.dumps(out)  # must not raise


def test_exec_query_returns_serializable_summary(categorical_qid):
    result, summary = chat._exec_query({"question_id": categorical_qid})
    assert result is not None
    # the summary is fed back to Gemini as JSON, so it must serialize cleanly
    json.dumps(summary)
    assert summary["question"]["q_id"] == categorical_qid


def test_exec_query_numeric_summary_has_no_decimals(numeric_qid):
    _, summary = chat._exec_query({"question_id": numeric_qid, "group_by": "sexo"})
    json.dumps(summary)  # numeric means come back as Decimal from DuckDB → must be coerced


def test_exec_query_city_filter(numeric_qid, city_ids):
    result, summary = chat._exec_query(
        {
            "question_id": numeric_qid,
            "filters": [{"attribute": "city_id", "value": [city_ids["Monterrey"]]}],
            "group_by": "city_id",
        }
    )
    assert result is not None
    group_cols = result["counts"]["columns"][2:-1]
    assert group_cols == ["Monterrey"]


def test_exec_query_bad_question_returns_error(numeric_qid):
    result, summary = chat._exec_query({"question_id": "__does_not_exist__"})
    assert result is None
    assert "error" in summary
