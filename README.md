# HyperTest One

> **One Input. One Mission. One Complete Test Cycle.**

**HyperTest One** is an agent-native autonomous testing platform and AI test engineering workbench. It turns a PRD, source repository, and test environment into a governed end-to-end testing cycle: requirement analysis, risk identification, test design, test implementation, execution, evidence collection, findings, and verdict.

HyperTest One does not attempt to replace general-purpose coding agents such as Codex or Claude Code. It acts as the **Autonomous Testing Control Plane** that defines testing missions, maintains canonical testing state, governs agent proposals, executes tests through trusted runners, and produces evidence-backed quality decisions.

## Core model

```text
Requirement
    ↓
Risk
    ↓
Test Case
    ↓
Implementation
    ↓
Execution
    ↓
Evidence
    ↓
Finding
    ↓
Verdict
```

> **Agent produces intelligence. Runner produces facts. HyperTest produces decisions.**

## Foundational documents

The following documents define the project-wide product, architecture, protocol, and domain-model baseline. They should be treated as global guidance for implementation and future design decisions.

1. [HyperTest Whitepaper](docs/foundation/HYPERTEST_WHITEPAPER.md)
2. [HyperTest Technical Architecture](docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)
3. [Test Mission Protocol Specification](docs/protocol/TEST_MISSION_PROTOCOL.md)
4. [HyperTest Domain Model & State Machine Specification](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)

## Project principle

HyperTest One orchestrates **testing work**, not model reasoning. Agent harnesses remain replaceable; testing state, evidence, policy, history, and verdicts remain owned by HyperTest One.
