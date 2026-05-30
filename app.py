from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import gradio as gr
import httpx
from dotenv import load_dotenv


load_dotenv()

OUTPUT_DIR = Path("outputs")
MODEL_TIMEOUT = 20.0
SEARCH_TIMEOUT = 5.0
LLM_TIMEOUT = 120.0
ACE_TIMEOUT = 660.0
POLL_INTERVAL = 5
MAX_POLLS = 120

PREFERRED_LLM_MODELS = [
    "deepseek/deepseek-v4-flash",
    "deepseek-v4-flash",
    "xiaomi/mimo-v2.5-pro",
    "xiaomi/mimo-v2.5",
]
SUGGESTED_MODELS = {"deepseek/deepseek-v4-flash", "deepseek-v4-flash"}
SUGGESTED_SUFFIX = " (Suggested)"
BING_URLS = ("https://cn.bing.com/search", "https://www.bing.com/search")
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma")
MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


CSS = """
.gradio-container { max-width: 1320px !important; margin: 0 auto !important; }
.hero { padding: 14px 18px; border: 1px solid var(--border-color-primary); border-radius: 10px; }
.panel { border: 1px solid var(--border-color-primary) !important; border-radius: 10px !important; padding: 12px !important; }
.hint { color: var(--body-text-color-subdued); font-size: 0.92rem; }
"""


def required(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise gr.Error(f"{name} is required.")
    return value


def base_url(value: str) -> str:
    return required(value, "Base URL").rstrip("/")


def headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def redact(message: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


def model_ids(data: Any) -> list[str]:
    ids: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            ids.append(value.strip())
        elif isinstance(value, dict):
            found = value.get("id") or value.get("name") or value.get("model")
            if isinstance(found, str) and found.strip():
                ids.append(found.strip())
            for key in ("data", "models", "result"):
                if key in value:
                    walk(value[key])
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return sorted(dict.fromkeys(ids))


def order_models(ids: list[str]) -> list[str]:
    preferred = [model for model in PREFERRED_LLM_MODELS if model in ids]
    return preferred + [model for model in ids if model not in preferred]


def model_label(model: str) -> str:
    return f"{model}{SUGGESTED_SUFFIX}" if model in SUGGESTED_MODELS else model


def model_id(label: str) -> str:
    label = required(label, "LLM model")
    return label[: -len(SUGGESTED_SUFFIX)] if label.endswith(SUGGESTED_SUFFIX) else label


def fetch_json(url: str, api_key: str, timeout: float = MODEL_TIMEOUT) -> Any:
    response = httpx.get(url, headers=headers(api_key), timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_llm_models(llm_base: str, llm_key: str) -> list[str]:
    llm_base = base_url(llm_base)
    llm_key = required(llm_key, "LLM API key")
    cache_key = ("llm", llm_base, key_hash(llm_key))
    if cache_key in MODEL_CACHE:
        return MODEL_CACHE[cache_key]
    try:
        models = order_models(model_ids(fetch_json(f"{llm_base}/models", llm_key)))
    except Exception as exc:
        raise gr.Error(redact(f"Failed to fetch LLM models: {exc}", llm_key)) from exc
    if not models:
        raise gr.Error("The LLM provider returned no model ids.")
    MODEL_CACHE[cache_key] = models
    return models


def fetch_ace_models(ace_base: str, ace_key: str) -> list[str]:
    ace_base = base_url(ace_base)
    ace_key = required(ace_key, "ACE API key")
    cache_key = ("ace", ace_base, key_hash(ace_key))
    if cache_key in MODEL_CACHE:
        return MODEL_CACHE[cache_key]

    for path in ("/v1/models", "/models"):
        try:
            models = model_ids(fetch_json(f"{ace_base}{path}", ace_key))
            if models:
                preferred = "acemusic/acestep-v1.5-turbo"
                models = [preferred] + [m for m in models if m != preferred] if preferred in models else models
                MODEL_CACHE[cache_key] = models
                return models
        except Exception:
            pass

    MODEL_CACHE[cache_key] = ["default"]
    return ["default"]


def fetch_models(llm_base: str, llm_key: str, ace_base: str, ace_key: str):
    with ThreadPoolExecutor(max_workers=2) as pool:
        llm_future = pool.submit(fetch_llm_models, llm_base, llm_key)
        ace_future = pool.submit(fetch_ace_models, ace_base, ace_key)
        llm_models = llm_future.result()
        ace_models = ace_future.result()

    labels = [model_label(m) for m in llm_models]
    preferred = model_label(llm_models[0])
    return (
        gr.update(choices=labels, value=preferred),
        gr.update(choices=ace_models, value=ace_models[0]),
        f"Fetched {len(llm_models)} LLM model(s) and {len(ace_models)} ACE model(s). Default: `{preferred}`.",
    )


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<.*?>", " ", value)).strip()


def bing_search(query: str, limit: int = 4) -> list[dict[str, str]]:
    params = {"q": f"{query} music arrangement BPM key references"}
    for url in BING_URLS:
        try:
            response = httpx.get(
                url,
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                timeout=SEARCH_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()
        except Exception:
            continue

        results: list[dict[str, str]] = []
        for block in re.findall(r"<li[^>]+class=\"b_algo\".*?</li>", response.text, flags=re.S):
            link = re.search(r"<h2.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, flags=re.S)
            snippet = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.S)
            title = strip_tags(link.group(2)) if link else ""
            href = html.unescape(link.group(1)).strip() if link else ""
            body = strip_tags(snippet.group(1)) if snippet else ""
            if title or body:
                results.append({"title": title, "url": href, "snippet": body})
            if len(results) >= limit:
                return results
        if results:
            return results
    return []


def direct_audio_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s\"'<>),]+", text or "")
    return [url for url in urls if urlparse(url).path.lower().endswith(AUDIO_EXTS)]


def search_terms(prompt: str) -> list[str]:
    prompt = prompt.replace("“", '"').replace("”", '"').replace("’", "'")
    quoted = re.findall(r'"([^"]+)"', prompt)
    artist_match = re.search(r"(?:edit|cover|remix)?\s*([a-z0-9 .&-]+?)(?:'s| by | - |:)", prompt, re.I)
    artist = artist_match.group(1).strip(" .-&") if artist_match else ""
    terms = []
    if quoted:
        terms += [" ".join(x for x in (artist, quoted[0]) if x), " ".join(quoted), quoted[0]]
    terms.append(prompt)
    return [term for term in dict.fromkeys(t for t in terms if t.strip())]


def itunes_preview(prompt: str) -> str | None:
    for term in search_terms(prompt):
        try:
            response = httpx.get(
                "https://itunes.apple.com/search",
                params={"term": term, "entity": "song", "limit": 5, "country": "us"},
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for item in data.get("results", []):
            url = item.get("previewUrl") if isinstance(item, dict) else None
            if isinstance(url, str) and urlparse(url).path.lower().endswith(AUDIO_EXTS):
                return url
    return None


def llm_messages(prompt: str, snippets: list[dict[str, str]], audio_hint: str | None) -> list[dict[str, str]]:
    system = """
You are a concise composer agent for ACE-Step music generation.
Return strict JSON only: {"candidates":[...]} with exactly 3 candidates.
Each candidate needs: title, concept, prompt, lyrics, bpm, key_scale,
time_signature, audio_duration, vocal_language, small_edit_instructions,
composition_plan, reference_audio_url, source_reference_query, ace_task_type.
Use section-tagged lyrics: [Intro], [Verse 1], [Chorus], [Bridge], [Outro].
For source edits/covers, preserve the source and change only what the user asks.
Do not reconstruct protected lyrics or melody from memory/search; use placeholders
and reference_audio_url when a verified URL is available. For new music, provide
a specific section/beat/chord/instrument/vocal/energy plan.
ace_task_type is "text2music" for new music and usually "cover" for edits.
""".strip()
    if audio_hint:
        system += f"\nVerified direct reference audio URL, use exactly when relevant: {audio_hint}"
    user = {
        "request": prompt,
        "search_snippets": snippets,
        "example_shape": {
            "candidates": [
                {
                    "title": "string",
                    "concept": "newly composed | edited from source | source-preserving",
                    "prompt": "render prompt",
                    "lyrics": "[Intro]\\n...\\n[Verse 1]\\n...\\n[Chorus]\\n...",
                    "bpm": 120,
                    "key_scale": "A Minor",
                    "time_signature": "4",
                    "audio_duration": 120,
                    "vocal_language": "en",
                    "small_edit_instructions": ["extend outro"],
                    "composition_plan": "specific plan",
                    "reference_audio_url": None,
                    "source_reference_query": None,
                    "ace_task_type": "text2music",
                }
            ]
        },
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def call_llm(llm_base: str, llm_key: str, llm_model: str, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": model_id(llm_model),
        "messages": messages,
        "temperature": 0.8,
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            f"{base_url(llm_base)}/chat/completions",
            headers=headers(required(llm_key, "LLM API key")),
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        if response.status_code >= 400:
            payload.pop("response_format", None)
            response = httpx.post(f"{base_url(llm_base)}/chat/completions", headers=headers(llm_key), json=payload, timeout=LLM_TIMEOUT)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        raise gr.Error(redact(f"LLM request failed: {exc}", llm_key)) from exc


def json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise gr.Error("LLM did not return valid JSON.")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise gr.Error("LLM JSON must include a candidates array.")
    return data


def normalize_candidate(value: dict[str, Any]) -> dict[str, Any]:
    def text(key: str, default: str = "") -> str:
        return str(value.get(key) or default).strip()

    def number(key: str, default: int) -> int:
        try:
            parsed = int(value.get(key))
            return parsed if parsed > 0 else default
        except Exception:
            return default

    edits = value.get("small_edit_instructions") or ["extend outro"]
    if isinstance(edits, str):
        edits = [line.strip() for line in edits.splitlines() if line.strip()]

    task_type = text("ace_task_type", "text2music").lower()
    if task_type not in {"text2music", "cover", "repaint", "lego", "extract", "complete"}:
        task_type = "text2music"

    ref = text("reference_audio_url") or None
    if ref and not ref.startswith(("http://", "https://")):
        ref = None

    return {
        "title": text("title", "Untitled"),
        "concept": text("concept", "newly composed"),
        "prompt": text("prompt", "music generation"),
        "lyrics": text("lyrics", "[Intro]\n...\n[Verse 1]\n...\n[Chorus]\n...\n[Outro]\n..."),
        "bpm": number("bpm", 120),
        "key_scale": text("key_scale", "C Major"),
        "time_signature": text("time_signature", "4"),
        "audio_duration": min(number("audio_duration", 120), 240),
        "vocal_language": text("vocal_language", "en"),
        "small_edit_instructions": edits if isinstance(edits, list) and edits else ["extend outro"],
        "composition_plan": text("composition_plan", "Render a complete, structured song."),
        "reference_audio_url": ref,
        "source_reference_query": text("source_reference_query") or None,
        "ace_task_type": task_type,
    }


def source_edit(prompt: str) -> bool:
    prompt = prompt.lower()
    return any(word in prompt for word in ("edit ", "cover ", "remix", "repaint", "keep the original", "preserve"))


def sanitize_source_candidates(prompt: str, candidates: list[dict[str, Any]], audio_hint: str | None) -> list[dict[str, Any]]:
    if not source_edit(prompt):
        return candidates
    safe_lyrics = (
        "[Intro]\n(Preserve reference intro.)\n\n"
        "[Verse 1]\n(Preserve reference vocal and lyric content.)\n\n"
        "[Chorus]\n(Preserve reference hook.)\n\n"
        "[Bridge]\n(Edit only as requested.)\n\n"
        "[Outro]\n(Preserve reference ending unless requested.)"
    )
    for candidate in candidates:
        candidate["lyrics"] = safe_lyrics
        candidate["ace_task_type"] = "cover"
        candidate["concept"] = "edited from source; preserve source audio when available"
        candidate["source_reference_query"] = prompt
        candidate["reference_audio_url"] = audio_hint or candidate.get("reference_audio_url")
    return candidates


def candidate_label(index: int, candidate: dict[str, Any]) -> str:
    return f"{index + 1}. {candidate['title']}"


def candidate_markdown(candidate: dict[str, Any] | None, index: int, snippets: list[dict[str, str]]) -> str:
    if not candidate:
        return f"### Candidate {index}\nGenerate samples to fill this tab."
    edits = "\n".join(f"- {item}" for item in candidate["small_edit_instructions"])
    return f"""
### {index}. {candidate['title']}
_Used {len(snippets)} Bing snippet(s)._

**Concept:** {candidate['concept']}  
**ACE task:** `{candidate['ace_task_type']}`  
**Metadata:** {candidate['bpm']} BPM, {candidate['key_scale']}, {candidate['time_signature']}/4, {candidate['audio_duration']}s, `{candidate['vocal_language']}`

**Generation prompt**  
{candidate['prompt']}

**Composition plan**  
{candidate['composition_plan']}

**Lyrics**
```text
{candidate['lyrics']}
```

**Small edits**
{edits}
""".strip()


def generate_candidates(llm_base: str, llm_key: str, llm_model: str, prompt: str):
    prompt = required(prompt, "Prompt")
    with ThreadPoolExecutor(max_workers=2) as pool:
        snippets_future = pool.submit(bing_search, prompt)
        audio_future = pool.submit(itunes_preview, prompt)
        snippets = snippets_future.result()
        audio_hint = audio_future.result()

    content = call_llm(llm_base, llm_key, llm_model, llm_messages(prompt, snippets, audio_hint))
    candidates = [normalize_candidate(item) for item in json_object(content)["candidates"][:3]]
    candidates = sanitize_source_candidates(prompt, candidates, audio_hint)
    while len(candidates) < 3:
        candidates.append(normalize_candidate({"title": f"Candidate {len(candidates) + 1}"}))

    labels = [candidate_label(i, c) for i, c in enumerate(candidates)]
    return (
        gr.update(choices=labels, value=labels[0]),
        candidates,
        candidate_markdown(candidates[0], 1, snippets),
        candidate_markdown(candidates[1], 2, snippets),
        candidate_markdown(candidates[2], 3, snippets),
    )


def selected_index(label: str) -> int:
    match = re.match(r"^(\d+)\.", label or "")
    if not match:
        raise gr.Error("Select a candidate before rendering.")
    return int(match.group(1)) - 1


def audio_format(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(url).path.lower()).suffix
    if suffix in (".m4a", ".aac"):
        return "mp4"
    if suffix in AUDIO_EXTS:
        return suffix.lstrip(".")
    if "wav" in content_type:
        return "wav"
    if "mp4" in content_type or "aac" in content_type:
        return "mp4"
    return "mp3"


def encode_reference(url: str) -> tuple[dict[str, str] | None, str]:
    try:
        response = httpx.get(url, timeout=ACE_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        raw = response.content
    except Exception as exc:
        return None, f"Reference lookup failed: {exc}"
    if len(raw) < 512:
        return None, "Reference lookup returned too little audio data."
    return (
        {"base64": base64.b64encode(raw).decode(), "format": audio_format(url, response.headers.get("content-type", ""))},
        f"Attached automatic reference audio ({len(raw):,} bytes).",
    )


def resolve_reference(candidate: dict[str, Any], prompt: str) -> tuple[dict[str, str] | None, str]:
    for url in [candidate.get("reference_audio_url"), *direct_audio_urls(prompt)]:
        if url:
            encoded, log = encode_reference(url)
            if encoded:
                return encoded, log
    if source_edit(prompt):
        found = itunes_preview(candidate.get("source_reference_query") or prompt)
        if found:
            return encode_reference(found)
    return None, ""


def ace_payload(candidate: dict[str, Any], ace_model: str, ref_audio: dict[str, str] | None) -> dict[str, Any]:
    model = ace_model if ace_model and ace_model != "default" else "acemusic/acestep-v1.5-turbo"
    if "/" not in model:
        model = f"acemusic/{model}"
    text = (
        f"{candidate['prompt']}\n\nLyrics:\n{candidate['lyrics']}\n\n"
        f"BPM: {candidate['bpm']}\nKey: {candidate['key_scale']}\n"
        f"Time: {candidate['time_signature']}/4\nDuration: {candidate['audio_duration']}s\n"
        f"Language: {candidate['vocal_language']}"
    )
    content: str | list[dict[str, Any]] = text
    if ref_audio:
        content = [{"type": "text", "text": text}, {"type": "input_audio", "input_audio": ref_audio}]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "thinking": True,
        "use_format": True,
        "use_cot_caption": True,
        "use_cot_language": True,
        "audio_config": {
            "format": "mp3",
            "duration": candidate["audio_duration"],
            "bpm": candidate["bpm"],
            "vocal_language": candidate["vocal_language"],
        },
    }
    if ref_audio:
        payload["task_type"] = candidate["ace_task_type"] if candidate["ace_task_type"] != "text2music" else "cover"
        payload["audio_cover_strength"] = 1.0
    return payload


def redact_audio(payload: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(payload))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "input_audio" in value and isinstance(value["input_audio"], dict):
                data = value["input_audio"].get("base64") or value["input_audio"].get("data")
                if isinstance(data, str):
                    value["input_audio"]["base64"] = f"[base64 audio omitted, {len(data):,} chars]"
                    value["input_audio"].pop("data", None)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(safe)
    return safe


def nested_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in nested_strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in nested_strings(item)]
    return []


def save_audio_item(ace_base: str, item: str) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    if item.startswith("data:"):
        suffix = ".mp3"
        match = re.match(r"data:audio/([^;,]+);base64,(.*)", item, flags=re.S)
        if match:
            suffix = ".wav" if "wav" in match.group(1) else ".mp3"
            item = match.group(2)
    else:
        resolved = urljoin(f"{base_url(ace_base)}/", item)
        if resolved.startswith(("http://", "https://")) and not re.fullmatch(r"[A-Za-z0-9+/=\s]+", item[:160]):
            suffix = Path(urlparse(resolved).path).suffix or ".mp3"
            output = OUTPUT_DIR / f"ace-{uuid.uuid4().hex}{suffix}"
            with httpx.stream("GET", resolved, timeout=ACE_TIMEOUT) as response:
                response.raise_for_status()
                output.write_bytes(b"".join(response.iter_bytes()))
            return str(output)
    output = OUTPUT_DIR / f"ace-{uuid.uuid4().hex}.mp3"
    output.write_bytes(base64.b64decode(item, validate=False))
    return str(output)


def find_audio_item(data: Any) -> str | None:
    for string in nested_strings(data):
        if string.startswith("data:audio/") or re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", string):
            return string
        if re.search(r"\.(mp3|wav|m4a|aac|flac|ogg)(\?|$)", string, re.I):
            return string
    return None


def hosted_ace(ace_base: str, ace_key: str, payload: dict[str, Any]) -> tuple[str, str]:
    response = httpx.post(
        f"{base_url(ace_base)}/v1/chat/completions",
        headers=headers(required(ace_key, "ACE API key")),
        json=payload,
        timeout=ACE_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    item = find_audio_item(data)
    if not item:
        raise gr.Error("ACE returned no audio item.")
    text = " ".join(str(s) for s in nested_strings(data)[:3])[:1200]
    return save_audio_item(ace_base, item), text


def native_ace(ace_base: str, ace_key: str, candidate: dict[str, Any], ace_model: str) -> str:
    payload = {
        "prompt": candidate["prompt"],
        "lyrics": candidate["lyrics"],
        "bpm": candidate["bpm"],
        "key_scale": candidate["key_scale"],
        "time_signature": candidate["time_signature"],
        "audio_duration": candidate["audio_duration"],
        "vocal_language": candidate["vocal_language"],
    }
    if ace_model and ace_model != "default":
        payload["model"] = ace_model
    response = httpx.post(f"{base_url(ace_base)}/release_task", headers=headers(ace_key), json=payload, timeout=LLM_TIMEOUT)
    response.raise_for_status()
    task_id = next((s for s in nested_strings(response.json()) if len(s) > 6), None)
    if not task_id:
        raise gr.Error("ACE /release_task response did not include a task id.")
    for _ in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        status = httpx.post(f"{base_url(ace_base)}/query_result", headers=headers(ace_key), json={"task_id": task_id}, timeout=LLM_TIMEOUT)
        status.raise_for_status()
        data = status.json()
        text = json.dumps(data).lower()
        if "fail" in text or "error" in text:
            raise gr.Error("ACE task failed.")
        item = find_audio_item(data)
        if item and ("success" in text or "complete" in text or "succeeded" in text):
            return save_audio_item(ace_base, item)
    raise gr.Error("ACE task timed out.")


def render(ace_base: str, ace_key: str, ace_model: str, selected: str, candidates: list[dict[str, Any]], prompt: str):
    if not candidates:
        raise gr.Error("Generate candidates before rendering.")
    candidate = candidates[selected_index(selected)]
    ref_audio, ref_log = resolve_reference(candidate, prompt)
    warning = ""
    if source_edit(prompt) and not ref_audio:
        warning = "\n\nReference audio was not found automatically, so this render is a text-only approximation."
        candidate = dict(candidate)
        candidate["ace_task_type"] = "text2music"

    payload = ace_payload(candidate, ace_model or "", ref_audio)
    log = ["## ACE progress / render log", ref_log, warning, "```json", json.dumps(redact_audio(payload), indent=2), "```"]
    yield "\n".join(part for part in log if part), None

    try:
        if (urlparse(base_url(ace_base)).hostname or "").lower() == "api.acemusic.ai":
            audio_file, response_text = hosted_ace(ace_base, ace_key, payload)
            yield "\n".join([*log, "\nCreated audio via hosted ACE.", response_text, f"\nSaved: `{audio_file}`"]), audio_file
        else:
            audio_file = native_ace(ace_base, ace_key, candidate, ace_model or "")
            yield "\n".join([*log, "\nCreated audio via native ACE.", f"\nSaved: `{audio_file}`"]), audio_file
    except Exception as exc:
        raise gr.Error(redact(f"ACE render failed: {exc}", ace_key)) from exc


def build_app() -> gr.Blocks:
    with gr.Blocks(title="ACE-Step Composer", fill_width=True) as demo:
        candidates = gr.State([])
        gr.Markdown("# ACE-Step Composer\n<span class='hint'>Search, compose candidates, render one with ACE.</span>", elem_classes=["hero"])
        with gr.Row():
            with gr.Column(scale=4, min_width=340):
                with gr.Group(elem_classes=["panel"]):
                    gr.Markdown("## Keys")
                    llm_base = gr.Textbox(label="LLM base URL", value=os.getenv("LLM_API_BASE", "https://api.openai.com/v1"))
                    llm_key = gr.Textbox(label="LLM API key", value=os.getenv("LLM_API_KEY", ""), type="password")
                    ace_base = gr.Textbox(label="ACE base URL", value=os.getenv("ACE_API_BASE", "https://api.acemusic.ai"))
                    ace_key = gr.Textbox(label="ACE API key", value=os.getenv("ACE_API_KEY", ""), type="password")
                with gr.Group(elem_classes=["panel"]):
                    gr.Markdown("## Compose")
                    prompt = gr.Textbox(label="Prompt", lines=6)
                    llm_model = gr.Dropdown(label="LLM model", choices=[], allow_custom_value=True)
                    gr.Markdown("DeepSeek V4 Flash is marked as Suggested when available.", elem_classes=["hint"])
                    ace_model = gr.Dropdown(label="ACE model", choices=["default"], value="default", allow_custom_value=True)
                    selected = gr.Dropdown(label="Candidate", choices=[])
                    with gr.Row():
                        fetch_btn = gr.Button("Fetch models")
                        gen_btn = gr.Button("Generate", variant="primary")
                    render_btn = gr.Button("Render with ACE", variant="primary")
            with gr.Column(scale=7, min_width=520):
                with gr.Group(elem_classes=["panel"]):
                    gr.Markdown("## Candidates")
                    with gr.Tabs():
                        with gr.Tab("Candidate 1"):
                            cand1 = gr.Markdown(candidate_markdown(None, 1, []))
                        with gr.Tab("Candidate 2"):
                            cand2 = gr.Markdown(candidate_markdown(None, 2, []))
                        with gr.Tab("Candidate 3"):
                            cand3 = gr.Markdown(candidate_markdown(None, 3, []))
                with gr.Group(elem_classes=["panel"]):
                    ace_log = gr.Markdown("## ACE progress / render log")
                    audio = gr.Audio(label="Final music", type="filepath")

        fetch_btn.click(fetch_models, [llm_base, llm_key, ace_base, ace_key], [llm_model, ace_model, ace_log])
        gen_btn.click(generate_candidates, [llm_base, llm_key, llm_model, prompt], [selected, candidates, cand1, cand2, cand3])
        render_btn.click(render, [ace_base, ace_key, ace_model, selected, candidates, prompt], [ace_log, audio])
    return demo


if __name__ == "__main__":
    build_app().launch(share=False, theme=gr.themes.Soft(), css=CSS)
