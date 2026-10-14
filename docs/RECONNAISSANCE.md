# Reconnaissance Report — AI Invoice-to-Order Reconciliation Agent (AMD Hackathon)

**Date:** 2026-10-14
**Author:** Senior Infrastructure & AI Systems Engineer (automated recon pass)
**Scope:** Inspect-before-implement. No application code was written; no large dependencies installed; no models downloaded; nothing committed or pushed.

Every significant finding below is tagged:
`VERIFIED` · `PARTIALLY VERIFIED` · `UNVERIFIED` · `BLOCKED`

---

## 1. Executive Summary

The repository is essentially **empty** (a single placeholder README, one grafted "Initial commit"). The local execution environment is a **CPU-only, 2-core / ~2 GiB RAM container** with **no AMD GPU, no ROCm, no Docker daemon, and no vLLM**. Network egress to PyPI, Hugging Face, and GitHub works. No Evolus or AMD Developer Cloud credentials exist in the environment, and no authoritative Evolus API documentation could be located from this sandbox.

**Consequences:**

* Local model serving on AMD hardware is **BLOCKED**. All AMD/vLLM feasibility work must move to AMD Developer Cloud (or an equivalent remote ROCm instance), which is **not yet provisioned or credentialed** here.
* Evolus integration readiness is **BLOCKED** pending workspace credentials and official API docs. Nothing about Evolus endpoints, auth schemes, or available blocks can be stated as fact yet — any such claim would be invented and is explicitly avoided in this report.
* Model selection was performed via **authoritative public HF Hub metadata only** (no downloads). Recommended initial candidate: **Qwen/Qwen2.5-7B-Instruct** (see §5). This recommendation is `PARTIALLY VERIFIED` — licensing/gating/size are verified facts; actual vLLM-on-ROCm inference remains untested until a GPU instance exists.

The definition of done for this mission (inspect, assess, evaluate without unsupported claims, produce this document, name next actions) is met. See §9 for the three prioritized next engineering actions.

---

## 2. Existing Repository Architecture

Location: `/workspace` (git repo). Evidence: `ls -la`, `git ls-files`, `git log`.

| Item | Finding | Status |
|---|---|---|
| Tracked files | Exactly one: `README.md` containing `# Repositorio-Enfoque-amd-act-III` + `README.md` (placeholder text) | VERIFIED |
| Source code | None (no `src/`, no `.py`/`.ts`/`.js` files) | VERIFIED |
| Frameworks | None present | VERIFIED |
| Dependency manifests / lockfiles | None (`requirements.txt`, `pyproject.toml`, `package.json` all absent) | VERIFIED |
| Tests / test infra | None | VERIFIED |
| Docker / container config | No `Dockerfile`, `docker-compose.yml`, or CI config in repo | VERIFIED |
| Env / secret conventions | No `.env*` files; no documented convention yet | VERIFIED |
| Evolus integration code | None | VERIFIED |
| AMD infra config / model-serving code | None | VERIFIED |
| Git state | Branch `qwen-code-7da7fa5e-4102-4dd3-9197-6d7a97a3d346`; `main` also exists at same ref; history is a single **grafted/shallow** commit `da3128b "Initial commit"`; working tree clean | VERIFIED |

Note: shallow (grafted) history means prior upstream commits, if any, are not retrievable locally. Preserve existing work = preserve the single README; nothing else was touched.

---

## 3. Verified Environment Inventory (Local Sandbox)

Evidence commands shown inline. The sandbox itself runs **inside a container** (`/.dockerenv` present; cgroup path `/k8s.io/…`) on Debian 12 (bookworm), x86_64.

| Tool / Resource | Result | Status |
|---|---|---|
| Python | 3.12.10 (`/usr/local/bin/python`) | VERIFIED |
| pip | 25.0.1 | VERIFIED |
| Node.js | v20.20.2 | VERIFIED |
| Git | 2.39.5 | VERIFIED |
| curl / jq | curl 7.88.1 / jq 1.6 | VERIFIED |
| Docker CLI | **Not found**; `docker info` fails (daemon unreachable) | BLOCKED (for local container builds) |
| CPU / RAM | 2 cores (`nproc`), ~2.1 GiB RAM (`free -h`) | VERIFIED |
| GPU devices | `/dev/dri` absent, `/sys/class/kfd` absent → **no GPU visible at all** (AMD or otherwise) | VERIFIED |
| ROCm | `/opt/rocm` absent; `rocminfo`/`rocm-smi`/`amd-smi` not on PATH | VERIFIED (absent) |
| PyTorch | Installed: **2.7.1+cu126** (NVIDIA CUDA build). `torch.cuda.is_available() → False`, `device_count → 0`. No ROCm build. | VERIFIED |
| transformers | 4.53.2 installed | VERIFIED |
| vLLM | **Not installed** (`pip show vllm` empty). Latest on PyPI: 0.31.0 (`pip index versions vllm`). | VERIFIED (absent locally) |
| Credentials / secrets | No env vars matching evolus/amd/vllm/hf/api-key patterns (checked with redaction). A `~/.netrc` exists but contains **no machine entries** relevant to us (grep for `machine` returned nothing). No HF token configured. | VERIFIED |
| Network egress | `pypi.org → 200`, `huggingface.co → 200`, `github.com → 200` | VERIFIED |

### Local vs. AMD Developer Cloud distinction
This sandbox is **only** a local development environment. There is **no evidence** that an AMD Developer Cloud instance has been provisioned, that any cloud account is linked, or that SSH/API access to one exists. Treat all AMD-GPU claims as remote-environment items to be verified after provisioning. Status: **BLOCKED / UNVERIFIED**.

---

## 4. AMD GPU, ROCm, PyTorch, and vLLM Compatibility Findings

* **No AMD GPU here.** `/dev/dri` (render nodes) and `/sys/class/kfd` (KFD) are both absent. Any "it runs" claim about GPU inference from this machine would be false. Status: VERIFIED (absence).
* **Installed PyTorch is a CUDA build**, not a ROCm build (`2.7.1+cu126`). It cannot target AMD GPUs even if one were attached. Status: VERIFIED.
* **vLLM AMD story (documentation-level, PARTIALLY VERIFIED):** vLLM publishes an official ROCm platform support path (prebuilt ROCm wheels/Docker images maintained by AMD for gfx942/MI300-class and other supported CDNA architectures). Authoritative references to confirm once on the cloud instance: `docs.vllm.ai` (GPU/ROCm setup pages) and `github.com/vllm-project/vllm` ROCm release images. We did **not** install vLLM locally because (a) there is no GPU, (b) only 2 CPU cores / 2 GiB RAM, and (c) the mission forbids unnecessary large installs.
* **Feasibility gate:** whether *our specific* AMD Developer Cloud allocation exposes a supported GPU architecture (e.g., MI300X gfx942 vs. other SKUs) determines the vLLM image choice. Unknown until the instance exists. Status: UNVERIFIED.
* **Verification plan (to run on the cloud instance, not here):**
  1. `rocminfo` / `amd-smi list` → capture ISA (expect `gfx942` for MI300 series).
  2. `python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"` against the **ROCm** torch build (on vLLM ROCm, `torch.cuda` maps to HIP devices).
  3. Pull AMD's published vLLM ROCm container for the matching ISA; launch `vllm serve <model>`; hit `/v1/models`, then a chat-completion request; confirm structured JSON output with guided decoding. Only after step 3 may "serving feasible" be marked VERIFIED.

---

## 5. Candidate-Model Comparison

Method: live queries to the **public Hugging Face Hub API** (`/api/models/<id>` incl. `safetensors` param counts and `gated` flags) on 2026-10-14. **No weights were downloaded.** BF16 VRAM estimate ≈ params × 2 bytes + KV-cache/engine overhead (roughly ≥20 GB total for a 7–8B model at useful context).

| Model | Params (BF16, from HF API) | Gated? | License | Structured JSON / tool use | Notes | Status |
|---|---|---|---|---|---|---|
| **Qwen/Qwen2.5-7B-Instruct** ✅ recommended | 7.62 B | No (`gated: false`) | Apache-2.0 per model card (re-confirm at pull time) | Strong instruction following; vLLM supports `guided_json`/structured outputs for the Qwen2 architecture | ~16 GB+ VRAM in BF16 → fits a single MI300X-class GPU comfortably; well-known vLLM ROCm recipes exist | PARTIALLY VERIFIED (hub facts verified; ROCm inference untested) |
| microsoft/Phi-3.5-mini-instruct | 3.82 B | No | MIT per model card (re-confirm) | Good JSON-following for its size; lower accuracy ceiling on reconciliation reasoning | Smallest footprint; designated fallback/dev-tier option if quota or latency demands it | PARTIALLY VERIFIED |
| meta-llama/Llama-3.1-8B-Instruct | 8.03 B | **Yes (`gated: manual`)** | Llama 3.1 Community License (usage restrictions apply) | Strong general capability + tool use | Requires Meta license approval + HF token acceptance before download — adds lead time and redistribution constraints for a public repo | PARTIALLY VERIFIED; gated = operational risk |

**Recommendation: Qwen2.5-7B-Instruct as the initial candidate.**
Evidence: ungated immediate availability (verified via HF API), permissive license compatible with hackathon/public-repo distribution, broad vLLM ecosystem support among the three, sufficient capacity for field-extraction + reconciliation-reasoning prompts, and modest memory needs for a single datacenter GPU. Phi-3.5-mini is the fallback (smaller/faster); Llama-3.1-8B is deferred due to gating friction.

Explicitly **not claimed**: any latency/throughput numbers, any successful inference run. Those require the GPU instance (§4 verification plan). Status of serving feasibility overall: **BLOCKED** locally; evaluation plan provided.

---

## 6. Evolus Integration Findings

Probing performed (HTTP status codes only; no fabricated endpoints):

| Probe | Result | Interpretation |
|---|---|---|
| `https://api.evolus.ai` | **404** on root | Host resolves/serves something, but we have **no documentation** confirming this is the product API base, nor any path/auth scheme. A 404 is not proof of a usable API. |
| `https://evolus.ai` | 308 redirect | Site live (marketing domain) |
| `https://www.evolus.ai` | 301 redirect | Site live |
| `https://docs.evolus.ai` | connection failed (000) | No docs at that host |
| HF search `evolus` | Only unrelated results (`evolusion-ai/Evo-70B-v1`, etc.) | No Evolus-platform artifacts found on HF hub |
| Local credentials/workspace | None (env scan, no `.env`, netrc has no machines, no SDK installed) | No workspace access configured |

Findings:

* **Which endpoints/auth methods are documented & accessible:** UNVERIFIED/BLOCKED. The only verifiable facts are DNS/TCP reachability of the vendor domains. We refuse to invent endpoint paths, parameter names, or authentication headers.
* **Which blocks exist in our workspace:** BLOCKED — requires tenant credentials. "Evolus" in this hackathon context ("Evolus Business Agents on AMD track") refers to the business-agent platform behind the challenge; its exact product surface must be confirmed from the hackathon brief/vendor documentation handed to us, not guessed. Status: UNVERIFIED.
* **Programmatic workflow invocation:** UNVERIFIED. Cannot be determined without official docs or console access.
* **Candidate ≥2-block mapping (design hypothesis only — clearly labeled, NOT verified):** a workflow of {document-field-extraction block} + {LLM-invocation / agent block} + {deterministic rules/decision block} + {webhook or persistence block for audit records} would satisfy the "at least two Evolus blocks via APIs" requirement **if** such blocks exist in the workspace. This is a requirement-traceability aid, not a claim about the actual catalog.
* **What remains missing:** API base URL + version, auth method (API key vs OAuth), workspace/tenant ID, block catalog listing, workflow trigger endpoint & payload schema, rate limits, and a test credential. All must come from the hackathon organizers' documentation package.

Status: **BLOCKED** pending credentials and official documentation.

---

## 7. Missing Credentials, Permissions, and Infrastructure Dependencies

1. **AMD Developer Cloud account + instance** (provisioning, SSH/API access, GPU SKU details) — missing entirely.
2. **Evolus workspace credentials + official API docs** — missing entirely.
3. **Hugging Face token** — not required for Qwen/Phi (ungated), required if the Llama fallback is chosen.
4. **Container runtime** — none locally (no Docker CLI/daemon); needed for the "containerized environment" requirement. Must be satisfied either on the cloud instance or via CI (e.g., GitHub Actions building the image).
5. **Git remote / publishing permissions** — no remote configured; public GitHub publication target TBD.
6. **Invoice + purchase-order sample data** — none in repo; needed for reconciliation rules and tests.

All six: **BLOCKED/UNVERIFIED** as of this report.

---

## 8. Blockers and Risks

| # | Blocker/Risk | Severity | Mitigation |
|---|---|---|---|
| B1 | No GPU/ROCm/Docker locally → cannot verify vLLM-on-AMD at all | High | Provision AMD Developer Cloud instance first; run §4 verification plan there |
| B2 | No Evolus credentials/docs → integration design is hypothetical | High | Request hackathon API access package immediately; keep app contract adapter-based so the Evolus client layer is swappable |
| B3 | Torch installed here is CUDA-flavored; naive `pip install vllm` would pull incompatible wheels and mislead | Medium | Never validate serving locally; use AMD's published vLLM ROCm container on the cloud instance |
| B4 | Sandbox is tiny (2 vCPU / 2 GiB) — even CPU smoke tests of a 7B model are impractical | Medium | Use the cloud instance for all model work; local scope limited to orchestration code + unit tests with a mocked LLM |
| B5 | Llama-3.1 gating/licensing friction if chosen | Low (avoided) | Recommendation already excludes it as primary |
| B6 | Shallow git history (grafted) may hide prior team work | Low | Confirm with team whether a fuller remote exists; fetch when remote is known |
| R1 | Treating `api.evolus.ai` 404 as proof of a usable API | — | Explicitly classified UNVERIFIED in §6; do not code against guessed paths |
| R2 | Requirement "run in containerized environment" unverifiable pre-Docker | — | Deliver Dockerfile + CI build; verify on the cloud instance where Docker exists |

---

## 9. Recommended Next Actions (ordered by dependency)

1. **[Unblocks B2 — highest priority, zero infra cost] Obtain the Evolus access package** from hackathon organizers: API base URL, auth scheme, workspace ID, block catalog, and a test key stored as an environment secret (never committed). Then perform an authenticated read-only call to enumerate blocks/workflows and update §6 with VERIFIED facts.
2. **[Unblocks B1] Provision the AMD Developer Cloud instance** (expected MI300X/gfx942 class), then execute the §4 verification checklist: `rocminfo`, ROCm-torch device check, launch `vllm serve Qwen/Qwen2.5-7B-Instruct` using AMD's published ROCm image, and validate a guided-JSON chat completion. Record outputs as evidence.
3. **[Depends on outcomes of 1 & 2; scaffold can start now] Establish the project skeleton** in this repo *without* new architecture assumptions: `docs/` (done), plus a planned `Dockerfile`, `requirements-dev.txt`, and a mocked-LLM reconciliation-rules module with pytest — keeping all Evolus/vLLM calls behind interfaces whose real implementations await verified endpoints. Publish branch (do not merge) for team review.

### Exact next command to recommend right now

On the future AMD Developer Cloud instance (once provisioned) — the single command that converts §4/§5 from plan to evidence:

```bash
docker run --device=/dev/kfd --device=/dev/dri --security-opt seccomp=unconfined \
  --group-add video --shm-size 16G --network host \
  <amd-published-vllm-rocm-image:matching-gfx942> \
  vllm serve Qwen/Qwen2.5-7B-Instruct --max-model-len 8192
```

(The exact image tag must be taken from AMD/vLLM's current ROCm release documentation at run time — deliberately not hardcoded here to avoid an unverified claim.)

Meanwhile, locally the very next concrete step is administrative: request Evolus credentials + docs (Action 1), since it gates the entire integration track.

---

## Appendix A — Raw Evidence Log (redacted)

```text
$ pwd && ls -la /workspace
/workspace ; only .git/ and README.md present

$ git status / branch / log
branch qwen-code-...-d346 (== main), clean tree; da3128b (grafted) "Initial commit"

$ python3 --version; pip --version; node --version; git --version; jq --version
3.12.10 ; 25.0.1 ; v20.20.2 ; 2.39.5 ; 1.6

$ docker --version; docker info
CLI not found; daemon not accessible

$ ls /dev/dri /sys/class/kfd /opt/rocm; which rocminfo rocm-smi amd-smi
all absent

$ python -c "import torch; ..."
torch 2.7.1+cu126 ; cuda/hip available: False ; device_count: 0

$ pip list | grep -iE 'vllm|transformers'
vllm absent ; transformers 4.53.2 ; pip index versions vllm -> latest 0.31.0 (not installed)

$ env scan for evolus/amd/token/secret (values redacted)
none relevant; ~/.netrc has no machine entries; no .env files

$ curl probes
pypi.org 200 | huggingface.co 200 | github.com 200
api.evolus.ai 404 | evolus.ai 308 | www.evolus.ai 301 | docs.evolus.ai 000

$ HF API (no downloads)
Qwen2.5-7B-Instruct : 7,615,616,512 BF16 params, gated=false, ~7.5M downloads
Phi-3.5-mini        : 3,821,079,552 BF16 params, gated=false
Llama-3.1-8B-Instruct: 8,030,261,248 BF16 params, gated=manual

$ container/host facts
/.dockerenv present; cgroup /k8s.io/...; Debian 12 bookworm; x86_64; 2 vCPU; 2.1 GiB RAM
```

*Secrets handling:* no credential values were printed anywhere in this session; env-var matches were masked with `***REDACTED***` before display. This document contains no secrets.
