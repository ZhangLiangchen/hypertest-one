"""Deliberately faulty SUT for real HTTP failure-diagnosis acceptance."""

from fastapi import FastAPI

from examples.api_sut.app import SumInput

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/sum")
def add(payload: SumInput) -> dict[str, int]:
    # Intentional, observable product defect: violates the specified sum API.
    return {"result": payload.a - payload.b}
