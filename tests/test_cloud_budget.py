"""Finite held accounting is separate from observed model requests and billing."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hypertest.api.cloud_schemas import CloudBudgetReservation, CloudBudgetSettlement
from hypertest.application.cloud_tasks import effective_budget_usage


def reservation(**updates):
    return {"profile": "cloud-budget-reservation/v1alpha1", "state": "HELD",
        "accounting_unit": "REQUEST_CREDITS", "reserved_seconds": 300,
        "request_limits": [{"scope": "ROOT", "max_requests": 10, "cost_per_request_microunits": 2},
            {"scope": "CODEX", "max_requests": 5, "cost_per_request_microunits": 3}],
        "reserved_cost_microunits": 35, **updates}


def test_lost_worker_hold_is_charged_without_mislabeling_it_as_observed_expenditure():
    attempt = SimpleNamespace(usage_seconds=3, cost_microunits=2,
        runtime_metadata={"budget_reservation": reservation()})
    assert effective_budget_usage(attempt) == (300, 35)
    assert attempt.usage_seconds == 3 and attempt.cost_microunits == 2
    attempt.usage_seconds = 302
    assert effective_budget_usage(attempt) == (302, 35)


def test_only_a_retained_settlement_record_releases_the_hold():
    proof = {"accounting_unit": "REQUEST_CREDITS", "observed_seconds": 3,
        "namespace_stopped": True, "brokers_drained": True,
        "requests": [{"scope": "ROOT", "requests": 1}, {"scope": "CODEX", "requests": 0}],
        "observed_cost_microunits": 2}
    attempt = SimpleNamespace(usage_seconds=3, cost_microunits=2,
        runtime_metadata={"budget_reservation": reservation(state="SETTLED", settlement=proof)})
    assert effective_budget_usage(attempt) == (3, 2)
    for change in [{"state": "SETTLED"}, {"reserved_cost_microunits": 1}, {"state": "UNKNOWN"}]:
        attempt.runtime_metadata = {"budget_reservation": reservation(**change)}
        with pytest.raises(HTTPException):
            effective_budget_usage(attempt)


def test_typed_reservation_and_settlement_reject_ambiguous_scopes_and_unstopped_runtime():
    with pytest.raises(ValidationError):
        CloudBudgetReservation(reserved_seconds=300, request_limits=[{"scope": "CODEX", "max_requests": 1, "cost_per_request_microunits": 1}])
    with pytest.raises(ValidationError):
        CloudBudgetReservation(reserved_seconds=300, request_limits=[{"scope": "ROOT", "max_requests": True, "cost_per_request_microunits": 1}])
    with pytest.raises(ValidationError):
        CloudBudgetSettlement(observed_seconds=3, namespace_stopped=True, brokers_drained=False, requests=[{"scope": "ROOT", "requests": 1}])
    with pytest.raises(ValidationError):
        CloudBudgetSettlement(observed_seconds=3, namespace_stopped=True, brokers_drained=True,
            requests=[{"scope": "ROOT", "requests": 1}, {"scope": "ROOT", "requests": 2}])
