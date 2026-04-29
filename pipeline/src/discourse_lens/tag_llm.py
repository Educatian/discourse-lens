"""LLM-based discourse-thread tagging via OpenRouter.

Each abstract is multi-label tagged against a curated taxonomy of 7
cross-field discourse threads. Uses Anthropic-style prompt caching on
the taxonomy + few-shot examples (stable prefix); OpenRouter passes
cache_control through to Anthropic-routed models.

Default model: anthropic/claude-sonnet-4.5 (override via DLENS_MODEL or
--model). For tagging, smaller models (gemini-2.0-flash, gpt-4o-mini)
also work and cut cost ~10x.

Two paths:
- sync: sequential httpx calls. Slow (~50min for 1500 abstracts) but
  simplest to debug.
- parallel: asyncio + semaphore-bounded concurrency. ~5min for 1500 at
  concurrency=10. OpenRouter has no Message Batches API equivalent, so
  this replaces the former Anthropic batch path.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from .cache import Cache
from .prep import doc_for_embedding

console = Console()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
MAX_TOKENS = 256

THREADS: list[dict] = [
    {
        "id": "scaffolding",
        "display_name": "Scaffolding & support",
        "definition": "Structures, prompts, fading, ZPD, instructional support - anything that helps learners do what they cannot yet do alone.",
    },
    {
        "id": "agency_srl",
        "display_name": "Learner agency / self-regulation",
        "definition": "Self-regulated learning, metacognition, learner control, choice, autonomy, self-efficacy, motivation as a learning resource.",
    },
    {
        "id": "dbr",
        "display_name": "Design-based research (LS-style)",
        "definition": "Design-based research as a learning-sciences method: iterative design experiments in real classrooms with conjecture maps and theory-testing across cycles. Use ONLY when the paper frames its work as DBR with theoretical conjecture-testing; for systematic instructional systems design / ID models / Type 1-2 design-and-development research, use id_systems instead.",
    },
    {
        "id": "id_systems",
        "display_name": "Instructional design & systems",
        "definition": "Instructional systems design (ISD), ADDIE/SAM/Dick-and-Carey, ID models like ARCS, 4C/ID, Merrill's First Principles, Gagne's events of instruction, and design-and-development research (Richey & Klein) studying ID processes and products. Systematic, model-driven design of instruction - distinct from LS design-based research which uses design as a vehicle to refine learning theory.",
    },
    {
        "id": "prof_dev",
        "display_name": "Professional development",
        "definition": "Teacher learning, in-service training, coaching, communities of practice for educators, faculty PD.",
    },
    {
        "id": "assessment_analytics",
        "display_name": "Assessment & analytics",
        "definition": "Formative or summative assessment, learning analytics, data-driven feedback, dashboards, automated assessment.",
    },
    {
        "id": "equity_access",
        "display_name": "Equity & access",
        "definition": "Underrepresented learners, marginalized populations, accessibility, justice, inclusion, the digital divide, culturally responsive design.",
    },
    {
        "id": "tech_integration",
        "display_name": "Technology integration",
        "definition": "Adoption, integration, or implementation of educational technology in instruction; AI, AR/VR, mobile, online/blended, gamification as means.",
    },
]

THREAD_IDS = [t["id"] for t in THREADS]


def _system_prompt() -> str:
    bullets = "\n".join(
        f"- **{t['id']}** ({t['display_name']}): {t['definition']}" for t in THREADS
    )
    return f"""You tag academic abstracts from Learning Sciences and Educational Technology journals against a fixed taxonomy of 7 cross-field discourse threads.

# Taxonomy

{bullets}

# Task

For each abstract, return JSON `{{"thread_ids": [...], "rationale": "..."}}` where:
- `thread_ids` is a list (0 to 3) of taxonomy IDs from the list above. Tag only threads the abstract clearly engages with - not threads that might be tangentially relevant.
- `rationale` is one short sentence explaining why those threads, citing words from the abstract.

If no thread fits, return `{{"thread_ids": [], "rationale": "no clear thread match"}}`. Be strict - empty is better than overinclusive.

Return ONLY the JSON object. No preamble, no markdown."""


FEW_SHOT_EXAMPLES: list[tuple[str, dict]] = [
    (
        "We designed and tested an online platform that supports student "
        "argumentation in middle-school science classrooms through structured "
        "prompts and peer feedback. Across three iterative design cycles, we "
        "refined the platform based on classroom observations and learner "
        "performance data.",
        {"thread_ids": ["scaffolding", "dbr"],
         "rationale": "Structured prompts (scaffolding) refined across iterative design cycles in classrooms (DBR)."},
    ),
    (
        "This study explores how preservice teachers integrate ChatGPT into "
        "their lesson planning. We surveyed 240 teacher candidates about "
        "their adoption patterns, perceived utility, and concerns about "
        "academic integrity.",
        {"thread_ids": ["tech_integration", "prof_dev"],
         "rationale": "Adoption of generative AI (tech_integration) by preservice teachers (prof_dev)."},
    ),
    (
        "This study reports the design and development of an online module "
        "for nursing skills training using the Dick and Carey instructional "
        "systems design model. We conducted three rounds of formative "
        "evaluation with subject-matter experts and target learners, "
        "iterating on the storyboards and assessment items based on feedback.",
        {"thread_ids": ["id_systems"],
         "rationale": "Dick & Carey ISD model with formative-evaluation cycles is classic instructional systems design (id_systems), not DBR theory-testing."},
    ),
    (
        "We present a literature review of 142 studies on classroom climate.",
        {"thread_ids": [],
         "rationale": "no clear thread match"},
    ),
]


def _cached_user_examples() -> list[dict]:
    blocks: list[dict] = []
    for i, (abstract, expected) in enumerate(FEW_SHOT_EXAMPLES):
        blocks.append({"type": "text", "text": f"Example {i+1} abstract:\n{abstract}"})
        blocks.append({"type": "text", "text": f"Example {i+1} response:\n{json.dumps(expected)}"})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _user_blocks_for_paper(text: str) -> list[dict]:
    return [{"type": "text", "text": f"Tag this abstract:\n{text}"}]


def _parse_response(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))
    try:
        obj = json.loads(text)
    except Exception:
        return {"thread_ids": [], "rationale": f"PARSE_ERROR: {text[:100]}"}
    obj["thread_ids"] = [tid for tid in obj.get("thread_ids", []) if tid in THREAD_IDS]
    return obj


def _load_dotenv() -> None:
    """Minimal .env loader - reads project-root .env without python-dotenv dep."""
    root = Path(__file__).resolve().parents[3]
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _get_api_key() -> str:
    _load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set (env var or project-root .env)")
    return api_key


def _resolve_model(model: str | None) -> str:
    return model or os.environ.get("DLENS_MODEL") or DEFAULT_MODEL


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Educatian/discourse-lens",
        "X-Title": "discourse-lens",
    }


def _build_payload(model: str, system_prompt: str, examples: list[dict], user_text: str) -> dict:
    """OpenAI-compatible chat payload; cache_control extension passes through to Anthropic routes."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]},
            {"role": "user", "content": examples + _user_blocks_for_paper(user_text)},
        ],
    }


def _extract_content_and_usage(data: dict) -> tuple[str, int, int]:
    msg = data["choices"][0]["message"]
    content = msg.get("content", "")
    if isinstance(content, list):
        text_parts = [b.get("text", "") for b in content
                      if isinstance(b, dict) and b.get("type") == "text"]
        content = "".join(text_parts) if text_parts else ""
    usage = data.get("usage", {}) or {}
    cache_read = int(usage.get("cache_read_input_tokens", 0) or
                     (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    return content, cache_read, cache_write


def _build_tag_record(row: dict, parsed: dict) -> dict:
    return {
        "thread_ids": parsed.get("thread_ids", []),
        "rationale": parsed.get("rationale", ""),
        "field": row["field"],
        "journal_id": row["journal_id"],
    }


def _build_error_record(row: dict, exc: Exception) -> dict:
    return {
        "thread_ids": [],
        "rationale": f"ERROR: {type(exc).__name__}: {str(exc)[:200]}",
        "field": row["field"],
        "journal_id": row["journal_id"],
    }


def _write_output(out_path: Path, model: str, tags: dict, cache_read: int, cache_write: int, n_rows: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "model": model,
        "provider": "openrouter",
        "taxonomy": THREADS,
        "tags": tags,
        "stats": {
            "n_abstracts": n_rows,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_write,
        },
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def _summarize(out_path: Path, tags: dict, n_rows: int, cache_read: int, cache_write: int) -> None:
    n_tagged = sum(1 for v in tags.values() if v["thread_ids"])
    n_err = sum(1 for v in tags.values() if v["rationale"].startswith("ERROR"))
    console.print(f"[green]tags.json -> {out_path}  ({n_tagged}/{n_rows} tagged, {n_err} errors)[/]")
    console.print(f"prompt cache: read={cache_read} tokens, write={cache_write} tokens")


def _load_rows(cache_path: str | Path, limit: int | None) -> list[dict]:
    cache = Cache(cache_path)
    rows = list(cache.iter_abstracts())
    if limit:
        rows = rows[:limit]
    if not rows:
        raise RuntimeError("Empty corpus")
    return rows


def tag_abstracts_sync(
    cache_path: str | Path,
    out_path: str | Path,
    limit: int | None = None,
    model: str | None = None,
) -> dict:
    """Sequential httpx calls; for smoke tests + small N."""
    api_key = _get_api_key()
    model = _resolve_model(model)
    rows = _load_rows(cache_path, limit)
    system_prompt = _system_prompt()
    examples = _cached_user_examples()

    tags: dict[str, dict] = {}
    cache_read = 0
    cache_write = 0

    with httpx.Client(timeout=120.0) as client, Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"tagging {len(rows)} via {model}", total=len(rows))
        for r in rows:
            doc_text = doc_for_embedding(r["title"], r["abstract"])
            payload = _build_payload(model, system_prompt, examples, doc_text)
            try:
                resp = client.post(f"{OPENROUTER_BASE}/chat/completions",
                                   headers=_headers(api_key), json=payload)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise RuntimeError(f"OpenRouter error: {data['error']}")
                content, cr, cw = _extract_content_and_usage(data)
                cache_read += cr
                cache_write += cw
                tags[r["doi"]] = _build_tag_record(r, _parse_response(content))
            except Exception as e:
                tags[r["doi"]] = _build_error_record(r, e)
            progress.update(task, advance=1)

    out_path = Path(out_path)
    _write_output(out_path, model, tags, cache_read, cache_write, len(rows))
    _summarize(out_path, tags, len(rows), cache_read, cache_write)
    return {"n": len(rows), "n_tagged": sum(1 for v in tags.values() if v["thread_ids"]), "tags": tags}


async def _tag_one_async(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system_prompt: str,
    examples: list[dict],
    row: dict,
    sem: asyncio.Semaphore,
) -> tuple[str, dict, int, int]:
    async with sem:
        doc_text = doc_for_embedding(row["title"], row["abstract"])
        payload = _build_payload(model, system_prompt, examples, doc_text)
        try:
            resp = await client.post(f"{OPENROUTER_BASE}/chat/completions",
                                     headers=_headers(api_key), json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"OpenRouter error: {data['error']}")
            content, cr, cw = _extract_content_and_usage(data)
            return row["doi"], _build_tag_record(row, _parse_response(content)), cr, cw
        except Exception as e:
            return row["doi"], _build_error_record(row, e), 0, 0


async def _run_parallel(
    rows: list[dict],
    model: str,
    api_key: str,
    concurrency: int,
) -> tuple[dict, int, int]:
    system_prompt = _system_prompt()
    examples = _cached_user_examples()
    sem = asyncio.Semaphore(concurrency)
    tags: dict[str, dict] = {}
    cache_read = 0
    cache_write = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"tagging {len(rows)} via {model} (concurrency={concurrency})",
                total=len(rows),
            )
            coros = [
                _tag_one_async(client, api_key, model, system_prompt, examples, r, sem)
                for r in rows
            ]
            for fut in asyncio.as_completed(coros):
                doi, record, cr, cw = await fut
                tags[doi] = record
                cache_read += cr
                cache_write += cw
                progress.update(task, advance=1)

    return tags, cache_read, cache_write


def tag_abstracts_parallel(
    cache_path: str | Path,
    out_path: str | Path,
    limit: int | None = None,
    model: str | None = None,
    concurrency: int = 10,
) -> dict:
    """Concurrent httpx.AsyncClient calls; replaces the former Anthropic batch path."""
    api_key = _get_api_key()
    model = _resolve_model(model)
    rows = _load_rows(cache_path, limit)

    tags, cache_read, cache_write = asyncio.run(
        _run_parallel(rows, model, api_key, concurrency)
    )

    out_path = Path(out_path)
    _write_output(out_path, model, tags, cache_read, cache_write, len(rows))
    _summarize(out_path, tags, len(rows), cache_read, cache_write)
    return {"n": len(rows), "n_tagged": sum(1 for v in tags.values() if v["thread_ids"]), "tags": tags}
