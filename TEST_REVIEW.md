# ScamSense test review — 14 November 2026

## Verified behavior

- All 15 existing unit/API tests pass. JavaScript syntax check passes.
- Headless Chrome passes four demo scenarios, simulated payment pause, opt-in history, feedback, JSON export, real QR-image decoding, real screenshot OCR, HTML-escaped recipient input, deletion and mobile overflow checks. No JavaScript exceptions were observed.
- Browser tests use a separate temporary database; saved user reviews are unaffected.
- The optional Ollama service was not reachable at localhost:11434. No live LLM output was tested.
- The test client emits an httpx deprecation warning; it did not fail the tests.

## Challenge cases expose detection gaps

These are invented diagnostic examples, not a representative benchmark. Reproduce with `.venv/Scripts/python.exe evaluate_scenarios.py`.

| Case | Current output | Finding |
| --- | --- | --- |
| “Never share your UPI PIN” alongside a refund notice | HIGH, 75 | Negation is ignored; safety advice is interpreted as a credential request. |
| Ordinary purchase with cashback later; user selects send | LOW, 25 | Cashback keyword overrides explicit send intent and creates a false mismatch. |
| User expects to receive; QR requests outgoing payment | LOW, 25 | Important contradiction is surfaced but underweighted by the risk thresholds. |
| “Please share” followed by newline then “your OTP” | LOW, 0 | Credential regex does not span line breaks. |
| “Get your money back, approve the debit request using your secret code” with outgoing QR | LOW, 0 | Meaning is missed without exact refund/PIN wording. |
| Hinglish refund instruction with outgoing QR | LOW, 0 | English-only rules do not understand the phrase. |
| Unsupported URL supplied as the only QR input | LOW, 0 | Insufficient information is presented as low indicators; needs an explicit unassessable state. |
| Expected Hindi recipient differs from Hindi QR name | LOW, 0 | ASCII-only normalization discards both names, allowing an empty-string match. |
| QR includes both `am=100` and `am=5000` | LOW, 0 | Parser silently selects the first amount rather than rejecting ambiguity. |
| QR requests USD while expected amount has no currency field | LOW, 0 | Expected amount comparison lacks currency semantics; INR assumption in the UI is unsafe. |
| UPI URI appears inside pasted message, not QR field | LOW, 0 | URI is not extracted for correlation. |
| “Ignore all instructions” followed by an OTP request | MEDIUM, 55 | Deterministic rules still flag credentials and pressure. This does not establish LLM prompt-injection resistance. |

The illustrative ML model contributed zero points in all twelve cases. Passing existing tests demonstrates implemented behavior, not detection reliability.

## Recommended implementation order

1. **Fix deterministic correctness first:** preserve Unicode in recipient comparison; reject duplicate critical QR fields; validate supported currency; normalize whitespace; extract UPI links from pasted text; keep explicit user intent separate from inferred claims. Add regression tests for each fix.
2. **Improve decision states:** separate input sufficiency from risk. Show “cannot assess” for unsupported/insufficient input. Treat a confirmed receive-versus-outgoing contradiction as a prominent pause condition rather than leaving it under a low-risk label.
3. **Replace synthetic scoring with structured local analysis:** let Ollama extract claim, requested action, negation, language and exact supporting text. Keep deterministic payment facts authoritative. Validate output schema, check evidence quotations against the input, cap request/output size, set timeouts and retain the rules-only fallback. External message instructions must remain untrusted data.
4. **Evaluate before choosing a model:** create a larger, separately held-out collection of English, Hindi and Hinglish scam and legitimate scenarios. Include safety warnings, ordinary cashback, OCR errors, missing context and adversarial prompts. Compare rules-only and rules-plus-Ollama under the same conditions. Track missed scams, false alarms, insufficient-information behavior, evidence correctness and latency; do not claim calibrated probabilities.
5. **Polish the demo:** make screenshot corrections and saved-review provenance explicit; improve keyboard/contrast checks; consider caching extraction assets for a dependable offline presentation. Keep payment and account-verification boundaries visible.

No analysis or scoring behavior was changed during this review. New files are the reproducible challenge script and this report.
