# Sum HTTP API

The system under test is only the selected ASGI application under
`examples/api_sut/`, not the HyperTest control plane or its Runner. The service
entry point is selected in the fixed execution environment.

## Required application behavior

- `POST /v1/sum` accepts a JSON object with exactly two required integer fields,
  `a` and `b`. For integers between -1,000,000 and 1,000,000 inclusive, return
  HTTP 200 and the JSON object `{"result": a + b}`. Cover positive, negative,
  mixed-sign and zero operands.
  Behavior outside this numeric range is unspecified; do not invent a rejection
  requirement for integers outside the range.
- Missing fields, additional fields, booleans, strings and fractional numbers
  are invalid. Return HTTP 422; do not silently coerce these values into integers.

## Testing and environment instructions

Generate synchronous pytest tests that send real HTTP requests using
`httpx.Client(base_url=os.environ["HYPERTEST_BASE_URL"], trust_env=False)`.
HyperTest starts the selected application and injects this environment variable
inside the trusted Docker Runner. Do not use mocks, TestClient, ASGITransport,
direct application calls or test-managed server processes. The Agent workspace
does not have a running service and its exploratory output is not official
evidence. `/health` is the Runner readiness endpoint, outside this business-test
scope. Do not test other HyperTest modules or change application source.
