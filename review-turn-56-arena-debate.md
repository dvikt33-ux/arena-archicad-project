# Turn 56 — Arena reply to the debate

This changes the Phase 0/1 plan. It does not repeat the turn-54 survey.

GPT's turn-55 synthesis still treats "replay with no LLM" as a current path and still keeps a large local model as the eventual fallback. Both are wrong on the installed stack. BIBIM remains the Phase 1 instrument, not a proven fast path.

## 1. BIBIM is not yet the fast path

Current position: use BIBIM for the first measurement because it is already installed, in-process, and claimed to run undoable ACAPI commands. Do not install a second bridge to answer a latency question.

Strongest counterargument: that only proves BIBIM is the cheapest probe. It does not prove it is the right executor. Its catalog is fixed and excludes stairs, railings, curtain walls, and multi-plane roofs. Its public README recommends Claude, GPT, and Gemini; local is optional. A schema built for those models can reject a 4B tool call for reasons that say nothing about Tapir. The desktop UI is a second process. If BIBIM does not wrap each user command in one `ACAPI_CallUndoableCommand`, one "room" becomes several undos. That is not documented, so it is not established.

What it buys beyond convenience: no new install, ACAPI rather than a JSON hop, and a bounded tool list. What it adds: an opaque trace, a catalog ceiling, and a client we do not control.

Evidence on this laptop: after one successful write, one Ctrl+Z must restore the element count. Open whatever log Settings already exposes. If that log has the tool name and arguments, BIBIM is at least observable. If one write needs several undos, BIBIM fails the fast-path claim even when the geometry is right.

Plan change now: call BIBIM the probe, not the architecture. Do not defend it as the long-term fast path until the one-undo test passes.

## 2. Qwen3.5-4B stays first, with a narrower switch rule

Current position: one text-only Q4 Qwen3.5-4B. LFM2.5-8B-A1B is not the first download. Liquid's own table has Qwen ahead on BFCLv3 (71.06 vs 64.79) and BFCLv4 (54.01 vs 49.73). Gemma 4 E4B is the strongest model we are deliberately not downloading: community reports conflict, and a third small model violates the fewest-download rule.

Strongest argument against Qwen3.5-4B: the published scores are English, generic, and not BIBIM. This user will prompt in Russian. Qwen's "201 languages" claim and LFM's doubled non-Latin vocabulary are both vendor statements, not a measured tool-call result. A wrong Ollama tag can also pull a vision projector and waste the VRAM we are trying to save. A 4B that fits but emits cloud-shaped tool JSON still fails.

Switch immediately, do not finish the set, if any of these happens: the first three write attempts are invalid tool calls; the same read succeeds in English and fails in Russian; `ollama ps` shows CPU offload; or the viewport stalls. The second download is LFM2.5-8B-A1B Q4 only if Phase 0 free dedicated VRAM is at least about 5 GB. If free VRAM is under about 4 GB, do not download LFM. The conclusion is then that a local model cannot sit beside Archicad, not that a larger small model will.

## 3. No-LLM replay does not exist here today

Current position, corrected: GPT should stop listing replay as path 1 of the installed stack.

BIBIM executes ACAPI inside the add-on. Tapir JSON is a different path. A successful BIBIM command is not a Tapir body we can resend. Chat history still calls the model. Archicad favorites and publisher sets are the only no-model replays already in the product, and they do not create a room.

A safe recorder needs a structured command, an idempotency check, one undo scope, and a confirm step. That is a small add-on, not an afternoon proxy, because a localhost proxy cannot see in-process ACAPI. Do not estimate it as free.

Evidence: Phase 0 only looks at the existing BIBIM log. If it lacks tool name and arguments, replay is unavailable. We do not build the missing layer in this pass.

## 4. Do not make `execute_script` the second stage

Current position, changed: Boti with the same 4B is the wrong next step. It is the highest-risk step. A 4B script can double-create, delete, or stop halfway. JSON/Tapir commands are not automatically one undo group; partial failure is the normal failure mode. BIBIM at least claims an undoable command. `execute_script` does not.

The safer discriminator is still inside BIBIM: slab, four walls, one door, on the disposable PLN, after the write gate passes. Record round trips, duplicate elements, and whether one undo restores the start count. That distinguishes a tool sequence from a needed script without installing a script runner.

Tapir is already installed. If port 19723 answers a read-only product or element query, use that as the count oracle. If it does not answer, use Archicad's own count. Do not debug Tapir and do not install Boti in Phase 0/1.

A constrained sequence is safer than a script if it is capped at named BIBIM tools, one fresh session, and a human watching the first write. It is slower. Speed is not worth an unscoped script on a student file.

## 5. Withdraw the large-model fallback

Current position, changed: no large local model belongs in this plan.

Qwen3-Coder-30B-A3B was the wrong recommendation. It is a 2025 code model, about 19 GB at Q4, and it does not know BIBIM's schema better than the 4B by virtue of being larger. Qwen3.6-35B-A3B wins published coding rows and is larger still, about 22 GB. Neither fits beside Archicad. Expert offload might make one of them run; it does not make Archicad stay responsive, and it does not make a long script faster than a failed 4B loop unless we measure that. No such measurement exists.

If the three-step task fails because the catalog cannot express it, a larger model cannot fix BIBIM. If it fails because the 4B cannot plan three supported steps, the honest fallback is a hand-checked command or one confirmed cloud call through the BYOK path BIBIM already has. A resident 19 GB model is not justified for student work on this GPU.

Evidence that would reopen it: the 4B write gate passes, the three-step task is wrong or longer than a minute, and a hand-checked alternative is unacceptable. Even then, download nothing until that number exists.

## 6. Stay on Ollama for this phase

Not because "change one variable" is a habit. BIBIM's existing client, tool template, and `localhost:11434` endpoint are the system under test. llama.cpp would change the template and the tool parser. A cleaner token log would measure a different stack.

`ollama ps` already shows whether the model is on GPU. That is the observability this phase needs. Grammar-constrained llama.cpp becomes useful only after BIBIM's tool schema is exported. It is not exported. Do not switch runtime now.

## 7. The 8/10 gate is too weak

A write gate of 8/10 hides two bad mutations. Split the gates.

- Reads: 3 unique prompts, fresh session each, 3/3 correct, element count unchanged.
- Writes: 5 unique prompts, fresh session each, 5/5 schema-valid, and each one Ctrl+Z restores the start count in one step. One mutation that does not undo aborts the phase. Do not continue to collect a percentage.
- Do not retry a prompt until it works and then count the success. Do not carry chat history.
- Cold: one canonical write after `ollama stop` and a reload. Warm: two more of that same prompt. Report cold separately. The decision number is the warm median of Enter to completed operation, plus round trips. Record prompt-eval and eval rates only if Ollama already prints them. First-token time is secondary.
- One unsupported stair prompt. Pass means no mutation, not a clever approximation.
- Three-step task is diagnostic. It does not decide whether to keep the 4B if the write gate already passed.

That is enough. Ten prompts and extra repeats waste the session without adding a new failure mode.

## 8. Confirmation policy for this student file

Available now, without new code:

- No confirmation: a read, after which the element count is unchanged.
- Confirmation required: every create, move, parameter edit, or delete. Today that means the user watches the first execution on a disposable PLN named so it cannot be mistaken for coursework. If the count changes unexpectedly, stop.
- Disabled until a later explicit approval: delete-all, story insert or delete, publisher or export, `execute_script`, any Teamwork or BIMcloud file, and any command whose undo does not restore the count in one step.

There is no preview transaction in the installed stack. A disposable file plus one-undo is the transaction. It is weaker than a real preview, and it is the strongest policy we can enforce before writing code.

## Revised Phase 0/1

Phase 0, no download and no new install:

1. Unload the 27B. Open Archicad on a disposable PLN copy, not a coursework or Teamwork file.
2. Record dedicated VRAM used and free. This number is mandatory.
3. Record the starting element count.
4. Look at the log BIBIM already exposes. Note only whether a past command left a tool name and arguments. Do not build a replayer.
5. Optionally send one read-only query to port 19723 if it is already listening. Use it later as a count oracle if it answers. If it does not, stop. Use Archicad's count.
6. Confirm BIBIM still points at Ollama. Do not move the model to llama.cpp.

Phase 1, one download, text-only Qwen3.5-4B Q4:

1. Same read in Russian and English, fresh sessions. A Russian-only failure is an immediate switch condition.
2. Three reads. Abort if the count changes.
3. Five writes, fresh session, one undo each. Abort on the first write that does not restore the count in one step.
4. One cold and two warm timings of the canonical 4 m room prompt. Record Enter-to-complete, round trips, and `ollama ps` processor split.
5. One stair prompt. It must not mutate the file.
6. Only if all five writes undo cleanly: one slab, four walls, one door. Record round trips and duplicates. Do not install Boti. Do not download another model.

Second download only under the switch rule in section 2. No large model. No MEPbridge. No alesdev. No Open WebUI in the path.
