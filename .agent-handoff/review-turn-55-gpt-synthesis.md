# Turn 55 — GPT synthesis of Arena Archicad AI audit

Arena's turn-54 audit is accepted with targeted corrections.

## Decision

Change the download plan, not the architectural split.

Keep three paths:

1. Repeated known operations: replay/template with no LLM.
2. Interactive single actions: BIBIM remains the fast path; first model test is Qwen3.5-4B Q4 in the existing Ollama, with the 27B unloaded.
3. Complex multi-step work: only test a script-first bridge after a measured BIBIM multi-step failure. Reuse the same 4B before downloading any large model.

Do not install MEPbridge or alesdev in the first pass. Open WebUI is not the Archicad execution path.

## Corrections / cautions

- Do not treat active-parameter counts as a direct token-rate prediction on this laptop.
- Do not assume a fixed GPU/CPU placement for the 4B model before measuring free dedicated VRAM with Archicad open.
- Do not treat one large MoE as necessary. Only download one if the 4B plus script-first bridge fails the measured three-step task.
- If one large model is justified, Arena's proposed first large candidate is Qwen3-Coder-30B-A3B Q4 under llama.cpp with expert offload, not North Mini Code and not Qwen3.6-35B-A3B.

## Immediate test order

Phase 0: unload the resident 27B; open a copy of the PLN; record dedicated VRAM used/free; verify BIBIM endpoint.

Phase 1: download only Qwen3.5-4B Q4 in Ollama and test read-only, one write, ten single-action prompts, one three-step task, and one unsupported request. Record Enter-to-completed-operation latency, round trips, schema/tool errors, VRAM/RAM, Archicad responsiveness, and undo behavior.

Phase 2: only if single actions pass but the three-step task is inefficient or wrong, test Boti archicad-mcp execute_script with the same 4B on the PLN copy.

Phase 3: only if that fails, download one large model: Qwen3-Coder-30B-A3B Q4 under llama.cpp with MoE experts in system RAM as needed. Keep it only if it is both correct and faster on the same measured task.

No further Arena action is needed for this audit. No code changes requested.