# HyperTest One — Claude Code Guidance

> **One Input. One Mission. One Complete Test Cycle.**

Claude Code must treat `AGENTS.md` and the four foundational documents below as repository-wide architecture guidance before making structural changes:

- `docs/foundation/HYPERTEST_WHITEPAPER.md`
- `docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md`
- `docs/protocol/TEST_MISSION_PROTOCOL.md`
- `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md`

The key rule is: **HyperTest orchestrates testing work, not model reasoning.** Claude Code is a replaceable Agent Harness / Testing Worker. It may reason, inspect repositories, edit code, invoke tools and debug, but Canonical Testing State, official execution evidence and final quality decisions remain owned by HyperTest.

Follow the precedence and non-negotiable principles in `AGENTS.md`.
