# ScamSense — Understand before you pay

Context-aware payment safety prototype for the Paytm AI Hackathon. Based on the pitch by **Gande Lahari · Team supercode**.

ScamSense connects what a sender claims with what a UPI payment requests. An incoming-refund story paired with an outgoing-payment QR gets a specific explanation, rather than a generic alert.

## Run locally (Windows)

Python 3.11–3.13 recommended. From this folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

The prepared `.venv` can be reused; skip creation and installation when dependencies are already installed. If using uv instead:

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Open **http://127.0.0.1:8000**. API docs: **http://127.0.0.1:8000/docs**.

## A two-minute judging demo

1. Select **Fake refund**, then **Review this payment**. Inspect the mismatch between receiving money and an outgoing QR, the PIN request, and urgency evidence.
2. Open **Review payment**. This is an explicitly simulated preview; pause and verify without authorizing anything.
3. Select **Wrong recipient**. Compare the expected store and amount with the QR. Both mismatches contribute evidence.
4. Try **KYC pressure** and **Store payment** to compare the explanations. Low indicators do not mean verified safety.
5. Add your own caller context, expected recipient and amount, or upload a screenshot / QR image. Correct OCR text before review.
6. Enable **Save this review on this laptop**, analyze again, provide usefulness feedback and open **Saved reviews**. Export a JSON review or delete saved reviews.

## What works

- Responsive browser workspace, screenshot OCR (Tesseract.js) and image QR decoding (jsQR).
- Explicit send / receive intent plus message and caller context.
- UPI parsing: recipient address, display name, amount and currency.
- Deterministic rules for intent, recipient and amount mismatches, PIN-for-refund, credential sharing, urgency, KYC pressure, suspicious domain patterns, advance fees and remote access.
- Evidence with point contributions, missing context, recommended next step and a simulated payment preview.
- Task/job/deposit/commission/tier/withdrawal-access/YouTube-liking/Telegram wording, plus investment or guaranteed-return wording, paired with an outgoing UPI request adds 50 points once and triggers a HIGH-severity 75-point floor. Matching is case-insensitive and uses word boundaries across the message and caller story. This broad keyword rule is an indicator, not verified fraud.
- A real scikit-learn TF-IDF / logistic-regression model, trained locally on first use on **32 synthetic illustrative examples**. It demonstrates integration, not production detection quality. Its signal adds 10 points at or above a 0.75 threshold; it cannot lower rule evidence. High-severity rules, validated HIGH local-LLM assessments, and heuristic totals that reach the former 60-point high threshold enforce a final floor of 75. Final scores are capped at 100; HIGH is 75–100 and MEDIUM starts at 30. Rule/ML contributions and applied floor reasons remain visible separately.
- Optional local Ollama context analysis, with an evidence-template fallback. Validated HIGH model output enforces a 75-point final score floor and cannot downgrade high-severity deterministic findings.
- Opt-in SQLite review storage, explanation-usefulness feedback and JSON export.

## Optional local LLM

The current app loads `SCAMSENSE_OLLAMA_MODEL` from the ignored project `.env`. When configured, local context analysis is selected by default. It reads the original message and context, validates structured findings and checks supporting quotations. A validated HIGH assessment raises the final risk score to at least 75; a lower assessment never reduces a stronger rule result. Unavailable, ungrounded or invalid model outputs do not receive a score override. The UI shows the final merged decision, raw rule/ML contributions and floor reasons. Critical refund and utility-verification warnings come from parsed facts, keeping payment authorization requirements explicit.

To start both Ollama (if stopped) and the web app on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_scamsense.ps1
```

The selected model must already be downloaded. First model load and CPU inference may take time; the app uses a 180-second local request timeout, with a minimum of 60 seconds for Ollama callers. `/health` reports `ollama_reachable`, `llm_model` and `llm_ready`, so configured and actually available are distinguished.

Install and run Ollama separately, pull an available model, and set its exact name before starting ScamSense:

```powershell
$env:SCAMSENSE_OLLAMA_MODEL = 'your-installed-model-name'
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

The backend calls only `http://127.0.0.1:11434/api/chat` for local analysis. User-shared messages are untrusted data in a separate user message. An unavailable model or output that fails schema/evidence validation falls back explicitly to the evidence template. Generated explanations remain model output and should be reviewed.

The parser accepts plain JSON or a single complete markdown JSON fence and normalizes structured labels such as `HIGH RISK`. It still rejects malformed/truncated responses, unsupported evidence and prose that only mentions “high risk.” Fallbacks include `llm_error_code` (`timeout`, `connection_error`, `invalid_json`, `schema_validation`, `truncated_response`, `evidence_validation`, `risk_conflict` or `provider_error`). Logs contain only the error code, not user inputs or model text. FASTag KYC blocking-pressure patterns and generic impersonation wording in QR names/notes enforce deterministic HIGH floors even when the model is unavailable. Generic wording is a heuristic indicator, not proof of fraud or identity.

Evidence grounding applies to quotations, not to the model's plain-language explanation or reasons. Benign extra JSON fields are ignored, and explanations may be up to 4,000 characters. Case, whitespace, Unicode and typographic punctuation differences are normalized. A misattributed quotation can be reassigned only when it occurs in exactly one real input field; unsupported or ambiguous quotations are still rejected. Source corrections are exposed by the shared analyzer for benchmark auditing.

## Architecture and deck mapping

| Pitch component | Working laptop adaptation |
| --- | --- |
| Kotlin / Jetpack Compose capture | Responsive browser inputs |
| ML Kit / ZXing extraction | Browser Tesseract.js / jsQR |
| Python / FastAPI backend | FastAPI with validated request schemas |
| Rules + ML | Evidence rules + illustrative scikit-learn model |
| Open-source LLM | Optional local Ollama |
| PostgreSQL audit / feedback | Local SQLite, opt-in saved reviews |
| Intervention before payment | Simulated review and a pause recommendation |

No native Android app, live Paytm access or PostgreSQL deployment is claimed. These remain future integration work.

## Privacy and limitations

- Inputs are sent to the local backend. Raw messages, caller context and uploaded images are not stored in review history. Saved evidence and payment details can contain names and UPI addresses. Use invented demo data.
- Reviews are not saved unless selected. SQLite lives in `data/scamsense.db`, which is ignored by Git. History and feedback are shared by anyone who can access this local server; there is no authentication. Keep it on loopback for demos.
- Images are processed in the browser. OCR / QR libraries and OCR language files are downloaded from third-party CDNs on demand. Manual paste works without these downloads; fonts have system fallbacks.
- A display name is not a verified account owner. Domain heuristics are not live reputation checks. Rules and the tiny synthetic model can miss scams and produce false alarms.
- Neither risk scores nor model outputs are validated fraud probabilities. No measured recall, false-positive rate or prevention claim is made. Saved usefulness feedback is not a verified fraud outcome and does not retrain the model.
- The app never initiates, authorizes or blocks payments and has no Paytm partnership or integration.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest -v
node --check static/app.js
# Optional end-to-end verification (requires installed Google Chrome):
.\.venv\Scripts\python.exe browser_check.py
```

API tests isolate their SQLite database in a temporary directory. Coverage includes context-dependent mismatches, safe sample behavior, malformed QR data, invalid amounts, score caps, request validation, opt-in storage, feedback, deletion and LLM fallback.

The browser check starts an isolated server on port 8001 with a temporary database. It exercises four scenarios, simulated review, saving, feedback, export, actual QR decoding and screenshot OCR, escaped inputs, deletion and mobile overflow. Preview screenshots are written to the ignored `artifacts/` directory.
