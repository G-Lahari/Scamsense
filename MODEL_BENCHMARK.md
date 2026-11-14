# ScamSense model evaluation

The model must understand the relationship between the sender's claim, requested action and decoded payment, including negation, paraphrases, Hindi and Hinglish.

## Local candidates

### Current app status — 14 November 2026

`qwen3:4b` is downloaded and configured in the ignored `.env`. Ollama and ScamSense have been started as background processes. `/health` confirms the selected model is installed and the service is reachable. The UI selects local context analysis by default.

Live checks completed through the application:

- A paraphrased refund request asking to approve a debit returned HIGH, with grounded message and QR quotations. First request took approximately 53.7 seconds including model loading.
- The browser submitted a “never share your PIN/OTP” safety notice and displayed a LOW local-model assessment. This warm request took approximately 22.7 seconds. Its explanation included an unsupported reference to an ordinary purchase, so evidence-quote validation does not establish full explanation correctness.
- All 22 unit/API tests and the existing rules-only browser regression flow pass. Browser verification also confirms the model is selected by default and renders an actual generated context assessment.

This is an enabled demo model, not the winner of a completed multi-model benchmark. Gemma comparison and the full challenge suite remain outstanding. The legacy heuristic score is still displayed separately and can disagree with the local model.

- `qwen3:4b`: text reasoning candidate, tested with thinking disabled for interactive latency.
- `gemma3:4b`: alternative multilingual candidate, tested using the same text-only input.

These quantized models are candidates for this 16 GB Windows laptop. Ollama currently reports CPU inference. Hardware suitability is a hypothesis until measured. The models are downloaded by Ollama outside the source checkout.

## Reproduce

Start Ollama, then from the project folder:

```powershell
ollama pull qwen3:4b
ollama pull gemma3:4b
.\.venv\Scripts\python.exe benchmark_models.py --provider ollama --model qwen3:4b
.\.venv\Scripts\python.exe benchmark_models.py --provider ollama --model gemma3:4b
```

Run inference sequentially so models do not compete for limited memory. Requests use a 4096-token context, temperature zero, bounded output and a 120-second timeout. Qwen thinking is disabled. Network downloads are separate from benchmark latency. First-request time includes model loading; reports also include median latency.

The benchmark runs up to 20 invented challenge cases and writes incremental JSON reports under `artifacts/benchmarks/`. Reports include expected review action, actual output, rules-only baseline, schema errors, exact-quote grounding, per-case latency and token usage. It stops early on initial provider/schema failures. No model is made the app default merely by running the benchmark.

## How to interpret results

- Labels encode intended review behavior, not verified fraud outcomes.
- Cases include known weaknesses from the initial review. This is a development set, not a held-out production accuracy test.
- Count missed HIGH cases and false alerts on LOW cases separately from overall agreement.
- A grounded quote appears in the input after Unicode/whitespace normalization. This alone does not prove the model's reasoning follows from the quote; manually inspect explanations.
- Invalid, truncated, unsupported or ungrounded outputs must not become trusted app decisions.
- Instruction-injection cases test untrusted message handling. Passing a few examples does not establish general prompt-injection resistance.
- Choose acceptable safety behavior first, then latency and memory. If neither model meets those needs, do not claim a winner.

## Sarvam deferred

Sarvam support is prepared but no paid calls are made without explicit benchmark authorization. When requested later, set `SARVAM_API_KEY` in the ignored project `.env`, then run a bounded benchmark with `--provider sarvam --model sarvam-105b --allow-paid`. Do not put API keys in command arguments, chat, benchmark output or source control. Reports contain synthetic case results and token usage, not secrets.

## Official references

- [Ollama Qwen3 4B](https://ollama.com/library/qwen3:4b)
- [Ollama Gemma 3 4B](https://ollama.com/library/gemma3:4b)
- [Ollama chat and structured output API](https://docs.ollama.com/api/chat)
- [Sarvam Chat Completion V2](https://docs.sarvam.ai/api-reference/chat/chat-completions-v2)
