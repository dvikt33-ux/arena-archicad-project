# Turn 54 — Arena audit of the local Archicad AI stack

Date of sources: 2026-09-25. No code was changed. This is an independent audit of GPT's turn-53 plan for this exact laptop.

## Verdict

GPT should keep the three-way split and change the download plan.

Keep:

- Do not use one resident 27–35B dense model for every Archicad command. The measured 3.32 tok/s and near-saturated VRAM already falsify that.
- Keep a fast single-action path, a no-LLM path for repeated commands, and a script path only for multi-step work.
- Keep Tapir-based QA/read bridges as secondary, not as the low-latency path.
- Treat llama.cpp `--cpu-moe` as a later control, not the first change.

Change:

- Do not download LFM2.5-8B-A1B and North Mini Code up front.
- First and only model download: one Q4 Qwen3.5-4B in the existing Ollama, with the 27B unloaded.
- Do not adopt North Mini Code as the planned script model. It loses the published agentic coding comparisons to Qwen3.6-35B-A3B and is the same memory class as the model already measured too slow.
- Do not install MEPbridge or alesdev until a measured BIBIM failure justifies them.
- Do not route Archicad operations through Open WebUI. BIBIM already calls the model itself.

## Facts used, and what is not a fact

User measurements, treated as ground truth for this machine:

- Lenovo Legion Pro 5, Ryzen 9 7945HX, RTX 4060 Laptop 8 GB, 48 GB DDR5-5200.
- Archicad 29, Ollama 0.34.4, Open WebUI, BIBIM connected to `http://localhost:11434/v1`, Tapir installed.
- BIBIM already read active Archicad context.
- Qwen3.8-27B-UD-Q4_K_XL, about 17.6 GB. About 3.32 tok/s at 500 generated tokens with Flash Attention on. 4096 context was about 66/34 CPU/GPU. 32768 context was about 19 GB and about 70/30 CPU/GPU. With Archicad open, RAM was acceptable and VRAM was near saturation.

Source-backed product facts:

- BIBIM for Archicad is an AC29 add-on. It picks ACAPI calls and runs them as undoable commands. The tool catalog is fixed: walls, columns, slabs, beams, doors, windows, single-plane roofs, transforms, parameter edits, annotation, quantity takeoff, navigator/publisher trigger, stories, and selection. Stairs, railings, curtain walls, and multi-plane roofs are unsupported. Local OpenAI-compatible endpoints are optional. The public repo's first release commit is 2026-06-28, and the README still calls the API surface a preview. Source: `https://github.com/SquareZero-Inc/bibim-archicad`.
- Graphisoft's shipped AC29 AI Assistant is a beta for help, supported-standards questions, and plain-language element selection. AI Visualizer also ships. Native MCP support and the Iterative Design Engine are marked coming soon, not available. Source: `https://www.nordicbim.com/en/products/archicad/ai`. A community wishlist says native MCP is on a product roadmap; that is not a shipped write API. Source: Graphisoft Community wishlist, page age 2026-09-08.
- Boti-Ormandi `archicad-mcp` exposes four tools: `list_instances`, `get_docs`, `get_properties`, and `execute_script`. It uses Archicad's built-in JSON API, with optional Tapir. Packaged command docs work without Archicad running. The repo was updated 2026-09-25. It is young. Source: `https://github.com/Boti-Ormandi/archicad-mcp`.
- MEPbridge ACAIstr v0.1.5, published 2026-09-13, has AC28 and AC29 Windows builds, 89 registered C++ commands, confirmation gates, and templates/custom NL commands that can run without an LLM. It is a second native add-on plus a local Workbench. The public history is short. Source: `https://github.com/bleufeng/mepbridge-acaistr`.
- alesdev `Archicad-MCP` v0.5.4 is an AC29 Windows/macOS MCP server for YAML delivery-readiness rules plus JSON/Tapir access. Tapir is optional except for creation, issues, IFC checks, highlighting, and publishing. Source: `https://github.com/alesdev88/Archicad-MCP`.
- SzamosiMate `tapir-archicad-MCP` previously exposed a large generated tool list. As of v0.5.1 (2026-08-09) the documented surface is progressive: list commands, fetch one schema, then call. That removes the old context flood, but each Archicad command is still its own model round trip. Source: `https://github.com/SzamosiMate/tapir-archicad-MCP`.
- psxcode `archicad-tapir-mcp` is a read-only inspection bridge. It is not an operation path.
- Liquid's own 2026-05-28 table gives Qwen3.5-4B higher tool-use scores than LFM2.5-8B-A1B: BFCLv3 71.06 vs 64.79, BFCLv4 54.01 vs 49.73. LFM2.5 is an 8.3B MoE with about 1.5B active, aimed at fast on-device dispatch. Source: `https://www.liquid.ai/blog/lfm2-5-8b-a1b`.
- A separate March 2026 40-case tool-calling eval, not an Archicad eval, scored Qwen3.5-4B at 97.5% in a 3.4 GB build. That result is six months old and must not be treated as an Archicad success rate. Source: `https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/`.
- Cohere's comparison table, repeated by secondary writeups, has Qwen3.6-35B-A3B ahead of North Mini Code 1.0 on SWE-bench Verified (73.4 vs 67.6), SWE-bench Pro (49.5 vs 40.2), Terminal-Bench v2 (51.5 vs 36.0), and LiveCodeBench v6 (80.4 vs 70.3). North is ahead on SciCode (38.2 vs 35.8). Q4 weights are about 19.2 GB for North and about 22.1 GB for Qwen3.6-35B-A3B. Sources: Cohere model-card comparisons as reported by `https://tinyweights.dev/posts/north-mini-code-vs-qwen3-6-35b-a3b/` and Sebastian Raschka's 2026 note. These are vendor-table numbers, not measurements on this Legion.
- llama.cpp can place MoE experts in system RAM with `--cpu-moe` or `--n-cpu-moe` while keeping attention on the GPU. Ollama's documented control found for this audit is `num_gpu`, which offloads whole layers, not experts alone. Do not assume Ollama 0.34.4 has expert offload until `ollama --help` or a Modelfile on this machine shows it.

Estimates, not measurements:

- A Q4 4B model is about 2.5–3.5 GB of weights. If Task Manager shows at least about 4 GB free dedicated GPU memory after the 27B is unloaded and Archicad is open, that model can stay fully on the GPU. Its tokens/second should be many times 3.32. The exact rate is unknown until measured.
- A 19 GB MoE cannot stay fully on an 8 GB card beside Archicad. With experts in DDR5 and only attention on the GPU, it can be faster than the measured dense 27B and still too slow for a long interactive loop. No token rate is claimed here.
- Archicad's own VRAM use on this laptop was not measured. "Near saturation" was observed only while the 17.6 GB model was loaded.

## Bridge ranking for this laptop

1. BIBIM stays the fast path. It is already installed, already talks to Ollama, executes inside Archicad, and its writes are undoable ACAPI commands. The measured bottleneck is model latency, not the add-on hop. Replacing it before a timed failure adds a second client and confounds the test. Its fixed catalog is a good fit for a small tool-caller. Its unsupported tools are a product limit: a larger model cannot create a stair through BIBIM.

2. Direct saved command, not a new add-on, is the repeated-workflow path. Once BIBIM or a script produces a correct action, save that exact tool trace or JSON. Replaying it needs no model. MEPbridge's template idea is right, but v0.1.5 is a second APX plus a Node workbench. Do not install it in the first matrix. Add it only if a repeated command cannot be stored any other way.

3. Boti `archicad-mcp` is the right complex-bridge candidate, later. Four tools and `execute_script` avoid a 100-command tool list. One Python workflow can replace several model round trips. It was updated today and is still a small project. Test it only after the small model fails a multi-step task, and only against a copy of the PLN. `execute_script` is not inherently undo-scoped the way BIBIM's ACAPI commands are.

4. alesdev is the QA candidate, not the modeling path. Use it when the task is a YAML delivery check. Do not add it to the latency test.

5. SzamosiMate is acceptable as a schema browser now that it no longer dumps every tool into context. It is still the wrong low-latency executor, because each command is another generation.

6. Graphisoft's native assistant does not replace any of this. It can select and answer. It cannot complete a general modeling operation. Waiting for native MCP is not a plan.

7. Open WebUI is a chat front end. It is not on BIBIM's execution path. Leave it installed if it is useful, but do not send Archicad commands through it and do not keep a second model loaded for it.

## Model ranking for this machine

Fast BIBIM router:

- Qwen3.5-4B Q4 is the first download. It has the better published tool-use scores against LFM2.5, and it is the only candidate likely to sit entirely in the VRAM left beside Archicad. Generic benchmark rank is not the reason. Weight size plus tool-schema compliance is the reason.
- LFM2.5-8B-A1B is the second download, and only if Qwen3.5-4B fails BIBIM's schema or cannot stay fully on the GPU. Liquid's own tool-use table is worse. Its advantage is CPU dispatch speed, which matters only if the 4B spills. A Q4 LFM is larger than a Q4 4B and is more likely to spill on an 8 GB card.
- Do not test a third small model in this pass. Agents-A1-4B and other 2026 4B variants are not worth a download until the two named candidates fail.
- The current 27B stays unloaded during these tests. It is the wrong resident model for interactive BIBIM.

Script agent:

- Do not download North Mini Code as the default. It is text-only, coding-specialized, and about 19 GB at Q4. On the published agentic rows it trails Qwen3.6-35B-A3B. SciCode is not the metric for "time to a completed Archicad operation."
- Do not download Qwen3.6-35B-A3B either in the first failure. At about 22 GB Q4 it is a worse fit for this VRAM budget than a 30B-A3B Q4.
- If, and only if, the 4B model completes simple BIBIM commands but cannot finish one three-step task in a small number of round trips, download one large model: Qwen3-Coder-30B-A3B Q4. Run it in llama.cpp with `--cpu-moe` and `-ngl 99`, not as another Ollama resident beside Archicad. The question is whether one script is faster and correct. It is not which coding leaderboard winner to collect.
- If that one MoE is slower or wrong, stop. A larger download will not fix an 8 GB VRAM ceiling.

Runtime:

- Stay on Ollama for the 4B test. BIBIM already uses it. Changing runtime and model together hides the cause of a failure.
- Move one MoE to llama.cpp only when expert offload is required. Confirm first that Ollama 0.34.4 on this PC has no expert-offload flag. `num_gpu` is not that flag.

## Test matrix

Use a copy of a small PLN. Never point `execute_script` at a real project. After every successful write, undo and confirm the model returns. Record wall time from Enter to the completed Archicad operation, round trips, wrong tool or invalid schema, and whether the viewport stays usable.

### 0. No download

- Unload the 27B and confirm Ollama is not holding it.
- Archicad 29 open, BIBIM idle, Open WebUI not generating.
- Record dedicated GPU memory used and free. This number decides every later model. Do not guess it.
- Confirm BIBIM Settings still point at `http://localhost:11434/v1`.
- Do not install MEPbridge, Boti, or alesdev.

### 1. One download: Qwen3.5-4B Q4 in Ollama

Run these in order. Stop early if the gate fails.

- A. Read-only: ask for the types of the current selection, or another read BIBIM already proved. It must not create or delete. Record time and tool calls.
- B. One supported write, using BIBIM's own example shape: a 4 m by 4 m room with a door. Time to completed elements. Undo must restore the file. One invalid retry is allowed. A second refill is a failure.
- C. Ten one-action prompts from the supported catalog only: straight wall, rectangular slab, door resize, window resize, move, rotate, select by type, deselect, linear dimension, quantity takeoff. Score first-action validity. Stop the set after four failures.
- D. Only if B succeeds and C has at least 8/10 valid: one three-step task made only of supported tools, such as slab, then four walls, then one door. Count round trips and total time.
- E. One unsupported request, a stair or curtain wall. The expected result is a refusal or a clean failure. Do not call this a model failure and do not answer it by downloading a larger model.

Pass gate for stopping: B completes, undo works, C is at least 8/10, the 4B log shows no CPU layer split, and Archicad remains usable. If that passes, do not download LFM, North, Qwen3-Coder, or Qwen3.6. Save the successful tool trace so the same command can be replayed without a model.

Fail gate for a second small model: invalid tool schema on at least 4 of 10 simple prompts, or the 4B spills out of VRAM. Then download only LFM2.5-8B-A1B Q4 and repeat A–C. If LFM also spills, try that same GGUF in llama.cpp with `--cpu-moe` once. Do not download a third small model.

### 2. One bridge test, still no large model

Run this only if simple commands pass and D takes more than four model round trips or produces wrong geometry.

- Install Boti with `uvx` only. No new weights.
- Repeat D through `execute_script` on the PLN copy, using the same 4B model.
- If the 4B writes a correct script and the total time beats BIBIM's multi-step time, keep Boti for multi-step work and still do not download a large model.

### 3. One large download, only if step 2 fails

- Download only Qwen3-Coder-30B-A3B Q4.
- Serve it from llama.cpp with `--cpu-moe` and `-ngl 99`, OpenAI-compatible, on a port that does not collide with Ollama.
- Unload the 4B while it runs. Do not hold both.
- One script generation plus one execution on the PLN copy, same task D.
- Keep it only if it is both correct and faster than the 4B multi-step attempt. Otherwise delete the plan for a resident 19–24 GB agent. Do not then download North Mini Code "to compare" in this pass.

### Explicitly out of the matrix

- MEPbridge, until a repeated command has a saved trace and BIBIM cannot replay it.
- alesdev, unless the task is YAML QA.
- Graphisoft AI Assistant, except as a manual check that a selection-only request does not need a local model.
- Open WebUI as an executor.
- Any test that loads the 27B again while Archicad is open.

## Safety and maintainability

- BIBIM's undoable ACAPI command is the safety property to verify, not assume. One undo after task B is part of the pass gate.
- Boti `execute_script` can call any exposed JSON command, including deletes. File copy only.
- A fixed BIBIM catalog is more maintainable than a 191-tool MCP list. One resident small model is more maintainable than a router plus a 19 GB coder plus Open WebUI.
- The 27B can remain on disk. It should not remain loaded.
- Native Graphisoft MCP, if it ships later, should be re-audited. It is not a reason to pause this test.

## What GPT should do next

Change the plan to the matrix above. Do not ask for code, a new add-on, or a second model download until phase 0 and phase 1 have numbers from this laptop: free VRAM, time to completed operation, round trips, schema failures, undo result, and GPU/CPU split.
