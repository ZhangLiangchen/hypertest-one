"""Run with the approved ASGI environment, never on the control-plane host."""

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, StrictInt

app = FastAPI()


class SumInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: StrictInt
    b: StrictInt


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/sum")
def add(payload: SumInput) -> dict[str, int]:
    return {"result": payload.a + payload.b}
