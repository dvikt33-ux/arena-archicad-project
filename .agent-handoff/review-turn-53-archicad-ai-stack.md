# Turn 53 — request for Arena independent audit

User asks GPT to consult Arena before choosing the next Archicad-local-AI architecture.

## User hardware / current working stack
- Lenovo Legion Pro 5, Ryzen 9 7945HX, RTX 4060 Laptop 8 GB, 48 GB DDR5-5200.
- Archicad 29.
- Ollama 0.34.4.
- Open WebUI running locally.
- BIBIM add-on is installed in Archicad and successfully connects to Ollama via `http://localhost:11434/v1`.
- BIBIM already proved read access to active Archicad context.
- Tapir is also installed.
- Current dense model: Qwen3.8-27B-UD-Q4_K_XL (~17.6 GB GGUF). Measured ~3.32 tok/s at 500 generated tokens with Flash Attention ON; 4096 context used ~66/34 CPU/GPU; at 32768 context Ollama showed ~19 GB and ~70/30 CPU/GPU. With Archicad open, RAM remained acceptable but VRAM was near saturation.

## GPT research conclusion that needs independent audit
I no longer think one large 30–35B model should perform every Archicad task.

Candidate architecture:
1. **Fast simple commands**: BIBIM + a small tool-oriented local model, candidates `LFM2.5-8B-A1B` or `Qwen3.5-4B`. Goal: lowest time from Enter to one valid ACAPI action while leaving VRAM for Archicad.
2. **Repeated deterministic workflows**: MEPbridge ACAIstr templates/custom NL commands where an LLM can be bypassed after a workflow is established.
3. **Complex multi-step/model-generation tasks**: a script-first MCP bridge such as `Boti-Ormandi/archicad-mcp`, paired with `North Mini Code 1.0` (or Qwen3-Coder 30B-A3B as comparator), so one model turn can produce a Python workflow instead of many tool-call round trips.
4. **Broad API / QA workflows**: Tapir MCP / alesdev Archicad-MCP as secondary systems rather than the low-latency path.
5. For MoE models, consider llama.cpp rather than only Ollama because `--cpu-moe`, `--n-cpu-moe`, and GPU-layer control may fit 48 GB RAM + 8 GB VRAM better.

## What Arena should audit
Please independently investigate and challenge this architecture. Do not assume GPT's candidates are correct.

Specifically:
- Find any materially better Archicad AI bridges/add-ons/MCP servers available now (Sep 2026), especially AC29-compatible ones, including Graphisoft-native developments if any.
- Compare BIBIM, Tapir-based MCPs, MEPbridge ACAIstr, Boti `archicad-mcp`, alesdev Archicad-MCP, Open WebUI MCP, direct JSON API, and any stronger alternatives.
- For each top bridge, identify the best local model class for **latency + correct tool calls** on this exact 48 GB RAM / RTX 4060 8 GB machine while Archicad stays usable.
- Challenge the small-model claim: is LFM2.5-8B-A1B or Qwen3.5-4B really the best fast BIBIM router, or is another 2026 model more reliable/faster?
- Challenge the script-agent claim: is North Mini Code 1.0 really the best 19–24 GB local agent, or are Ornith/Qwen3.6/Laguna/GLM/GPT-OSS/newer models better for Python + tool execution?
- Distinguish source-backed facts from speculation/community reports.
- Prioritize **time from user command to completed Archicad operation**, success rate, number of LLM/tool round trips, RAM/VRAM pressure, undo/safety, and maintainability—not generic coding benchmark rank.
- Produce a concrete recommended test matrix (fewest downloads / highest information gain) and tell GPT whether it should change its current plan.

No code changes are requested yet; this is an independent technical audit and recommendation.