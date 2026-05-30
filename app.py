from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
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
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0

PREFERRED_LLM_MODELS = [
    "deepseek/deepseek-v4-flash",
    "deepseek-v4-flash",
]
SUGGESTED_MODELS = {"deepseek/deepseek-v4-flash", "deepseek-v4-flash"}
SUGGESTED_SUFFIX = " (Suggested)"
BING_URLS = ("https://cn.bing.com/search", "https://www.bing.com/search")
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".mp4")
REFERENCE_TASKS = {"cover", "repaint", "lego", "extract", "complete"}
MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
REFERENCE_META: dict[str, str] = {}


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


def mentions(result: dict[str, str], term: str) -> bool:
    haystack = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
    return term.lower() in haystack


def page_context_windows(query: str, term: str, limit: int = 3) -> list[dict[str, str]]:
    pages = [
        ("https://m.baidu.com/s", {"word": query}),
    ]
    contexts: list[dict[str, str]] = []
    for url, params in pages:
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

        text = re.sub(r"<(script|style).*?</\1>", " ", response.text, flags=re.S | re.I)
        text = re.sub(r"\s+", " ", strip_tags(text))
        for match in re.finditer(re.escape(term), text, flags=re.I):
            start = max(match.start() - 120, 0)
            end = min(match.end() + 220, len(text))
            snippet = text[start:end].strip()
            if any(bad in snippet.lower() for bad in ("<link", "aria-", "rel=", "autocomplete=", "spellcheck=")):
                continue
            if snippet and all(snippet != item["snippet"] for item in contexts):
                contexts.append({"title": f"{term} search context", "url": str(response.url), "snippet": snippet})
            if len(contexts) >= limit:
                return contexts
    return contexts


def source_title(prompt: str) -> str:
    clean = re.sub(r"https?://\S+", "", prompt or "").strip()
    clean = clean.replace("“", '"').replace("”", '"').replace("《", '"').replace("》", '"')
    quoted = re.findall(r'"([^"]+)"', clean)
    if quoted:
        return quoted[0].strip()

    markers = [
        "改编成", "改编为", "改成", "改为", "改编", "改",
        "翻唱成", "翻唱为", "翻唱", "重混", "混音",
        "remix", "cover", "repaint", "edit",
    ]
    lower = clean.lower()
    positions = [lower.find(marker.lower()) for marker in markers if lower.find(marker.lower()) > 0]
    if positions:
        clean = clean[: min(positions)]
    clean = re.sub(r"^(把|将|请把|请将)\s*", "", clean).strip()
    clean = re.sub(r"['’]s$", "", clean).strip()
    return clean[:80]


def edit_target(prompt: str) -> str:
    markers = ["改编成", "改编为", "改成", "改为", "改编", "改", "翻唱成", "翻唱为", "remix", "cover", "edit"]
    lower = (prompt or "").lower()
    for marker in markers:
        pos = lower.find(marker.lower())
        if pos >= 0:
            return prompt[pos + len(marker):].strip()[:80]
    return ""


def music_context_search(prompt: str) -> list[dict[str, str]]:
    title = source_title(prompt)
    target = edit_target(prompt)
    queries = [prompt]
    if title and source_edit(prompt):
        queries = [
            f"{title} 歌曲 原唱 作曲 编曲 BPM 调性",
            f"{title} 官方 音频 试听 歌曲信息",
            f"{title} 歌曲 风格 节奏 编曲",
            f"{title} {target} 改编 编曲" if target else f"{title} 改编 编曲",
        ]

    snippets: list[dict[str, str]] = []
    seen: set[str] = set()
    for query in queries:
        for result in bing_search(query, limit=3):
            if title and source_edit(prompt) and not mentions(result, title):
                continue
            key = result.get("url") or result.get("title") or result.get("snippet", "")[:80]
            if key and key not in seen:
                snippets.append(result)
                seen.add(key)
            if len(snippets) >= 8:
                return snippets
        if title and source_edit(prompt):
            for result in page_context_windows(query, title, limit=3):
                key = result.get("url", "") + result.get("snippet", "")[:80]
                if key and key not in seen:
                    snippets.append(result)
                    seen.add(key)
                if len(snippets) >= 8:
                    return snippets
    return snippets


def bing_result_links(query: str, limit: int = 8) -> list[str]:
    links: list[str] = []
    for search in (
        f"{query} 试听 mp3 m4a wav",
        f"{query} official audio preview mp3 m4a",
        f"{query} site:music.163.com OR site:y.qq.com OR site:kuwo.cn OR site:kugou.com",
    ):
        for result in bing_search(search, limit=limit):
            url = result.get("url", "")
            if url and url not in links:
                links.append(url)
    return links[:limit]


def direct_audio_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s\"'<>),]+", text or "")
    return [url for url in urls if urlparse(url).path.lower().endswith(AUDIO_EXTS)]


def provider_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    referer: str = "",
) -> Any:
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if referer:
        request_headers["Referer"] = referer
    if method == "POST":
        request_headers["Content-Type"] = "application/json"
        response = httpx.post(url, headers=request_headers, json=payload or {}, timeout=SEARCH_TIMEOUT)
    else:
        response = httpx.get(url, headers=request_headers, params=params, timeout=SEARCH_TIMEOUT)
    response.raise_for_status()
    return response.json()


def search_terms(prompt: str) -> list[str]:
    prompt = prompt.replace("“", '"').replace("”", '"').replace("’", "'")
    quoted = re.findall(r'"([^"]+)"', prompt)
    artist_match = re.search(r"(?:edit|cover|remix)?\s*([a-z0-9 .&-]+?)(?:'s| by | - |:)", prompt, re.I)
    artist = artist_match.group(1).strip(" .-&") if artist_match else ""
    terms = []
    title = source_title(prompt)
    if title:
        terms.append(title)
    if quoted:
        terms += [" ".join(x for x in (artist, quoted[0]) if x), " ".join(quoted), quoted[0]]
    terms.append(prompt)
    return [term for term in dict.fromkeys(t for t in terms if t.strip())]


def reference_search_queries(prompt: str) -> list[str]:
    queries: list[str] = []
    for term in search_terms(prompt):
        queries.extend(
            [
                term,
                f"{term} 官方音频",
                f"{term} 官方MV",
                f"{term} 原唱",
                f"{term} 试听",
                f"{term} QQ音乐",
                f"{term} 网易云音乐",
                f"{term} 酷狗音乐",
                f"{term} official audio",
                f"{term} preview",
            ]
        )
    return [query for query in dict.fromkeys(q for q in queries if q.strip())]


def reference_meta_label(provider: str, title: str, artist: str = "", album: str = "", kind: str = "song") -> str:
    return " - ".join(part for part in (f"{provider} {kind}", title, artist, album) if part)


def netease_song_url(song_id: int) -> str | None:
    data = provider_json(
        "GET",
        "https://music.163.com/api/song/enhance/player/url",
        params={"ids": json.dumps([song_id]), "br": 320000},
        referer="https://music.163.com/",
    )
    for item in data.get("data", []):
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


def netease_mv_url(mvid: int) -> tuple[str | None, int | None]:
    data = provider_json(
        "GET",
        "https://music.163.com/api/mv/detail",
        params={"id": mvid, "type": "mp4"},
        referer="https://music.163.com/",
    )
    mv = data.get("data") if isinstance(data, dict) else None
    if not isinstance(mv, dict):
        return None, None
    brs = mv.get("brs")
    if not isinstance(brs, dict) or not brs:
        return None, mv.get("duration")
    def quality(item: tuple[str, Any]) -> int:
        try:
            return int(item[0])
        except Exception:
            return 0
    for _, url in sorted(brs.items(), key=quality, reverse=True):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url, mv.get("duration")
    return None, mv.get("duration")


def netease_reference(prompt: str) -> str | None:
    title = source_title(prompt)
    if not title:
        return None
    try:
        data = provider_json(
            "GET",
            "https://music.163.com/api/search/get/web",
            params={"s": title, "type": 1, "limit": 8, "offset": 0},
            referer="https://music.163.com/",
        )
    except Exception:
        return None
    songs = data.get("result", {}).get("songs", [])
    if not isinstance(songs, list):
        return None
    for song in songs:
        if not isinstance(song, dict):
            continue
        name = str(song.get("name") or "")
        if title not in name and not any(title in str(alias) for alias in song.get("alias", [])):
            continue
        artists = song.get("artists") if isinstance(song.get("artists"), list) else []
        artist = " / ".join(str(a.get("name") or "") for a in artists if isinstance(a, dict))
        album = song.get("album") if isinstance(song.get("album"), dict) else {}
        album_name = str(album.get("name") or "")
        song_id = song.get("id")
        if isinstance(song_id, int):
            try:
                url = netease_song_url(song_id)
            except Exception:
                url = None
            if url:
                REFERENCE_META[url] = reference_meta_label("NetEase", name, artist, album_name, "song")
                return url
        mvid = song.get("mvid")
        if isinstance(mvid, int) and mvid > 0:
            try:
                url, duration_ms = netease_mv_url(mvid)
            except Exception:
                url, duration_ms = None, None
            if url:
                meta = reference_meta_label("NetEase", name, artist, album_name, "official MV")
                if duration_ms:
                    meta += f" ({duration_ms / 1000:.1f}s)"
                REFERENCE_META[url] = meta
                return url
    return None


def qq_song_url(songmid: str) -> str | None:
    payload = {
        "req": {
            "module": "CDN.SrfCdnDispatchServer",
            "method": "GetCdnDispatch",
            "param": {"guid": "10000", "calltype": 0, "userip": ""},
        },
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": "10000",
                "songmid": [songmid],
                "songtype": [0],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
            },
        },
        "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
    }
    data = provider_json("POST", "https://u.y.qq.com/cgi-bin/musicu.fcg", payload=payload, referer="https://y.qq.com/")
    req = data.get("req_0", {}).get("data", {})
    info = req.get("midurlinfo", [{}])[0]
    purl = info.get("purl") if isinstance(info, dict) else ""
    if not purl:
        return None
    for sip in req.get("sip", []):
        if isinstance(sip, str) and sip.startswith(("http://", "https://")):
            return urljoin(sip, purl)
    return None


def qq_mv_url(vid: str) -> str | None:
    payload = {
        "getMvUrl": {
            "module": "gosrf.Stream.MvUrlProxy",
            "method": "GetMvUrls",
            "param": {"vids": [vid], "request_typet": 10001},
        },
        "comm": {"ct": 24, "cv": 0},
    }
    data = provider_json("POST", "https://u.y.qq.com/cgi-bin/musicu.fcg", payload=payload, referer="https://y.qq.com/")
    items = data.get("getMvUrl", {}).get("data", {}).get(vid, {}).get("mp4", [])
    if not isinstance(items, list):
        return None
    items = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda item: int(item.get("fileSize") or 0),
        reverse=True,
    )
    for item in items:
        for url in item.get("url", []):
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
    return None


def qq_reference(prompt: str) -> str | None:
    title = source_title(prompt)
    if not title:
        return None
    try:
        data = provider_json(
            "GET",
            "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
            params={"w": title, "format": "json", "p": 1, "n": 8},
            referer="https://y.qq.com/",
        )
    except Exception:
        return None
    songs = data.get("data", {}).get("song", {}).get("list", [])
    if not isinstance(songs, list):
        return None
    for song in songs:
        if not isinstance(song, dict):
            continue
        name = str(song.get("songname") or "")
        if title not in name:
            continue
        artists = song.get("singer") if isinstance(song.get("singer"), list) else []
        artist = " / ".join(str(a.get("name") or "") for a in artists if isinstance(a, dict))
        album = str(song.get("albumname") or "")
        songmid = str(song.get("songmid") or "")
        if songmid:
            try:
                url = qq_song_url(songmid)
            except Exception:
                url = None
            if url:
                REFERENCE_META[url] = reference_meta_label("QQ Music", name, artist, album, "song")
                return url
        vid = str(song.get("vid") or "")
        if vid:
            try:
                url = qq_mv_url(vid)
            except Exception:
                url = None
            if url:
                REFERENCE_META[url] = reference_meta_label("QQ Music", name, artist, album, "official MV")
                return url
    return None


def itunes_preview(prompt: str) -> str | None:
    wanted_title = source_title(prompt).lower()
    countries = ("cn", "hk", "tw", "us", "jp")
    for term in reference_search_queries(prompt):
        for country in countries:
            try:
                response = httpx.get(
                    "https://itunes.apple.com/search",
                    params={"term": term, "entity": "song", "limit": 10, "country": country},
                    timeout=SEARCH_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except Exception:
                continue
            fallback: str | None = None
            for item in data.get("results", []):
                if not isinstance(item, dict):
                    continue
                url = item.get("previewUrl")
                if not isinstance(url, str) or not urlparse(url).path.lower().endswith(AUDIO_EXTS):
                    continue
                track = str(item.get("trackName") or "").lower()
                collection = str(item.get("collectionName") or "").lower()
                artist = str(item.get("artistName") or "").lower()
                haystack = f"{track} {collection} {artist}"
                if wanted_title and wanted_title in haystack:
                    REFERENCE_META[url] = " - ".join(
                        part
                        for part in (
                            str(item.get("trackName") or "").strip(),
                            str(item.get("artistName") or "").strip(),
                            str(item.get("collectionName") or "").strip(),
                        )
                        if part
                    )
                    return url
                if not fallback:
                    fallback = url
                    REFERENCE_META[url] = " - ".join(
                        part
                        for part in (
                            str(item.get("trackName") or "").strip(),
                            str(item.get("artistName") or "").strip(),
                            str(item.get("collectionName") or "").strip(),
                        )
                        if part
                    )
            if fallback and not wanted_title:
                return fallback
    return None


def wider_reference_audio(prompt: str) -> str | None:
    for url in direct_audio_urls(prompt):
        return url
    for provider in (netease_reference, qq_reference):
        url = provider(prompt)
        if url:
            return url
    preview = itunes_preview(prompt)
    if preview:
        return preview
    for query in reference_search_queries(prompt):
        for url in bing_result_links(query):
            if urlparse(url).path.lower().endswith(AUDIO_EXTS):
                return url
    return None


def llm_messages(prompt: str, snippets: list[dict[str, str]], audio_hint: str | None) -> list[dict[str, str]]:
    title = source_title(prompt) if source_edit(prompt) else ""
    target = edit_target(prompt) if source_edit(prompt) else ""
    system = """
You are a concise composer agent for ACE-Step music generation.
Return strict JSON only: {"candidates":[...]} with exactly 3 candidates.
Each candidate needs: title, concept, prompt, lyrics, bpm, key_scale,
time_signature, audio_duration, vocal_language, small_edit_instructions,
composition_plan, ace_task_type.
Use section-tagged lyrics: [Intro], [Verse 1], [Chorus], [Bridge], [Outro].
For source edits/covers, every candidate must be an edit strategy for the same
detected source song. Do not create unrelated songs or alternate originals.
Preserve the source and change only what the user asks.
Do not reconstruct protected lyrics or melody from memory/search; use placeholders
for source lyrics/audio. The app, not you, decides whether reference search is needed
and finds reference audio. Do not return reference_audio_url, source_reference_query,
or needs_reference_search. For new music, provide
a specific section/beat/chord/instrument/vocal/energy plan.
For Chinese source-edit prompts like "孤勇者改成钢琴曲", treat the text before
"改成/改为/改编/翻唱" as the source song title and the text after it as the
requested arrangement edit. Do not invent a different song.
ACE task mapping:
- text2music: new music from silence, no reference needed.
- cover: source/cover/remix/edit with full-track target, reference needed.
- repaint: edit a section of existing audio, reference needed.
- extract: extract a stem from full music, reference needed.
- lego: add/layer track from source audio, reference needed.
- complete: complete a partial/single track into full track, reference needed.
""".strip()
    user = {
        "request": prompt,
        "app_detected_source_title": title or None,
        "app_detected_edit_target": target or None,
        "app_reference_policy": (
            "Reference search is required and handled by the app. Preserve the detected source song; "
            "your job is to describe the requested arrangement/edit."
            if title
            else "No source title detected by the app."
        ),
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
        "reference_audio_url": None,
        "reference_search_query": None,
        "needs_reference_search": False,
        "ace_task_type": task_type,
    }


def source_edit(prompt: str) -> bool:
    prompt = prompt.lower()
    return any(
        word in prompt
        for word in (
            "edit ", "cover ", "remix", "repaint", "keep the original", "preserve",
            "改成", "改为", "改编", "翻唱", "重混", "混音", "保留原曲", "保留", "原曲",
        )
    )


def instrumental_edit(prompt: str) -> bool:
    prompt = (prompt or "").lower()
    return any(
        word in prompt
        for word in (
            "钢琴曲", "钢琴版", "钢琴", "纯音乐", "伴奏", "无人声",
            "piano", "instrumental", "no vocal", "no vocals",
        )
    )


def needs_reference_search(prompt: str, candidate: dict[str, Any]) -> bool:
    return source_edit(prompt) or candidate.get("ace_task_type") in REFERENCE_TASKS


def candidate_is_instrumental(candidate: dict[str, Any]) -> bool:
    text = " ".join(
        str(candidate.get(key, ""))
        for key in ("prompt", "lyrics", "concept", "vocal_language")
    )
    return instrumental_edit(text) or str(candidate.get("vocal_language", "")).lower() in {
        "instrumental",
        "none",
        "no vocals",
        "no vocal",
    }


def sanitize_source_candidates(prompt: str, candidates: list[dict[str, Any]], audio_hint: str | None) -> list[dict[str, Any]]:
    app_query = " / ".join(reference_search_queries(prompt)[:3])
    title = source_title(prompt)
    target = edit_target(prompt)
    is_instrumental = instrumental_edit(prompt)
    safe_lyrics = (
        "[Intro]\n(Instrumental piano intro preserving the source motif.)\n\n"
        "[Verse 1]\n(Instrumental piano carries the original verse melody; no vocals.)\n\n"
        "[Chorus]\n(Instrumental piano states the original chorus hook clearly; no vocals.)\n\n"
        "[Bridge]\n(Instrumental bridge preserves source structure and harmony while applying the requested arrangement.)\n\n"
        "[Outro]\n(Instrumental piano outro preserving the source ending shape.)"
        if is_instrumental
        else
        "[Intro]\n(Preserve reference intro.)\n\n"
        "[Verse 1]\n(Preserve reference vocal and lyric content.)\n\n"
        "[Chorus]\n(Preserve reference hook.)\n\n"
        "[Bridge]\n(Edit only as requested.)\n\n"
        "[Outro]\n(Preserve reference ending unless requested.)"
    )
    for candidate in candidates:
        should_search = needs_reference_search(prompt, candidate)
        candidate["needs_reference_search"] = should_search
        candidate["reference_search_query"] = app_query if should_search else None
        candidate["reference_audio_url"] = audio_hint if should_search else None
        if source_edit(prompt):
            candidate["lyrics"] = safe_lyrics
            candidate["ace_task_type"] = "cover"
            candidate["concept"] = "edited from source; preserve source audio when available"
            edit_style = (
                "Render as an instrumental piano arrangement with no vocals. "
                "Keep the source melody, timing, section order, and emotional contour recognizable. "
                if is_instrumental
                else
                "Keep the source melody, vocals, timing, section order, and recognizable hooks unless the user explicitly asked to change them. "
            )
            candidate["prompt"] = (
                f"Preserve the original source song '{title}' as the musical source. "
                f"Apply only this requested edit: {target or prompt}. "
                f"{edit_style}"
                f"{candidate['prompt']}"
            )
    return candidates


def candidate_label(index: int, candidate: dict[str, Any]) -> str:
    return f"{index + 1}. {candidate['title']}"


def candidate_markdown(candidate: dict[str, Any] | None, index: int, snippets: list[dict[str, str]]) -> str:
    if not candidate:
        return f"### Candidate {index}\nGenerate samples to fill this tab."
    edits = "\n".join(f"- {item}" for item in candidate["small_edit_instructions"])
    ref_state = "Yes, app will search reference audio" if candidate.get("needs_reference_search") else "No"
    if candidate.get("reference_audio_url"):
        ref_state += " (automatic reference found)"
    return f"""
### {index}. {candidate['title']}
_Used {len(snippets)} Bing snippet(s)._

**Concept:** {candidate['concept']}  
**ACE task:** `{candidate['ace_task_type']}`  
**Reference search:** {ref_state}  
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
        snippets_future = pool.submit(music_context_search, prompt)
        audio_future = pool.submit(wider_reference_audio, prompt)
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


def probe_audio_duration(raw: bytes, fmt: str) -> float | None:
    suffix = f".{fmt}" if fmt else ".audio"
    if suffix == ".mp4":
        suffix = ".m4a"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as temp:
            temp.write(raw)
            temp.flush()
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    temp.name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        if result.returncode != 0:
            return None
        duration = float(result.stdout.strip())
        return duration if duration > 0 else None
    except Exception:
        return None


def compress_reference_audio(raw: bytes, fmt: str, max_seconds: int | None) -> tuple[bytes, str]:
    suffix = ".m4a" if fmt == "mp4" else f".{fmt or 'audio'}"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as src, tempfile.NamedTemporaryFile(suffix=".mp3") as dst:
            src.write(raw)
            src.flush()
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src.name,
                "-vn",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-b:a",
                "96k",
            ]
            if max_seconds:
                cmd += ["-t", str(max_seconds)]
            cmd += [dst.name]
            result = subprocess.run(cmd, check=False, capture_output=True, timeout=90)
            if result.returncode == 0 and Path(dst.name).stat().st_size > 512:
                return Path(dst.name).read_bytes(), "mp3"
    except Exception:
        pass
    return raw, fmt


def encode_reference(url: str, max_seconds: int | None = None) -> tuple[dict[str, Any] | None, str]:
    try:
        response = httpx.get(url, timeout=ACE_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        raw = response.content
    except Exception as exc:
        return None, f"Reference lookup failed: {exc}"
    if len(raw) < 512:
        return None, "Reference lookup returned too little audio data."
    fmt = audio_format(url, response.headers.get("content-type", ""))
    duration = probe_audio_duration(raw, fmt)
    sent_raw, sent_fmt = compress_reference_audio(raw, fmt, max_seconds)
    sent_duration = probe_audio_duration(sent_raw, sent_fmt)
    details = f"{len(raw):,} bytes"
    if duration:
        details += f", {duration:.1f}s"
    if sent_raw != raw:
        details += f"; sending compressed audio {len(sent_raw):,} bytes"
        if sent_duration:
            details += f", {sent_duration:.1f}s"
    meta = REFERENCE_META.get(url)
    label = f"Matched: {meta}. " if meta else ""
    return (
        {
            "base64": base64.b64encode(sent_raw).decode(),
            "format": sent_fmt,
            "duration": duration,
            "sent_duration": sent_duration,
            "url": url,
        },
        f"Attached automatic reference audio ({details}). {label}Source: {url}",
    )


def resolve_reference(candidate: dict[str, Any], prompt: str) -> tuple[dict[str, Any] | None, str]:
    max_seconds = int(candidate.get("audio_duration") or 0) or None
    for url in [candidate.get("reference_audio_url"), *direct_audio_urls(prompt)]:
        if url:
            encoded, log = encode_reference(url, max_seconds)
            if encoded:
                return encoded, log
    if candidate.get("needs_reference_search"):
        found = wider_reference_audio(candidate.get("reference_search_query") or prompt)
        if found:
            return encode_reference(found, max_seconds)
    return None, ""


def ace_payload(candidate: dict[str, Any], ace_model: str, ref_audio: dict[str, Any] | None) -> dict[str, Any]:
    model = ace_model if ace_model and ace_model != "default" else "acemusic/acestep-v1.5-turbo"
    if "/" not in model:
        model = f"acemusic/{model}"
    is_reference_task = ref_audio is not None
    is_instrumental = candidate_is_instrumental(candidate)
    lyrics_for_ace = "" if is_instrumental else candidate["lyrics"]
    lyrics_block = "Instrumental arrangement. No sung lyrics." if is_instrumental else lyrics_for_ace
    vocal_language = candidate["vocal_language"]
    text = (
        f"{candidate['prompt']}\n\nLyrics:\n{lyrics_block}\n\n"
        f"BPM: {candidate['bpm']}\nKey: {candidate['key_scale']}\n"
        f"Time: {candidate['time_signature']}/4\nDuration: {candidate['audio_duration']}s\n"
        f"Language: {vocal_language}"
    )
    content: str | list[dict[str, Any]] = text
    if ref_audio:
        content = [
            {"type": "text", "text": text},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": ref_audio["base64"],
                    "format": ref_audio["format"],
                },
            },
        ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": True,
        "thinking": not is_reference_task,
        "use_format": not is_reference_task,
        "use_cot_caption": not is_reference_task,
        "use_cot_language": not is_reference_task,
        "audio_config": {
            "format": "mp3",
            "duration": candidate["audio_duration"],
            "bpm": candidate["bpm"],
            "vocal_language": vocal_language,
            "is_instrumental": is_instrumental,
        },
    }
    if ref_audio:
        payload["task_type"] = candidate["ace_task_type"] if candidate["ace_task_type"] != "text2music" else "cover"
        payload["instruction"] = candidate["prompt"]
        payload["audio_cover_strength"] = 1.0
    return payload


def redact_audio(payload: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(payload))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "input_audio" in value and isinstance(value["input_audio"], dict):
                data = value["input_audio"].get("base64") or value["input_audio"].get("data")
                if isinstance(data, str):
                    if "data" in value["input_audio"]:
                        value["input_audio"]["data"] = f"[base64 audio omitted, {len(data):,} chars]"
                    else:
                        value["input_audio"]["base64"] = f"[base64 audio omitted, {len(data):,} chars]"
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
        output = OUTPUT_DIR / f"ace-{uuid.uuid4().hex}{suffix}"
        output.write_bytes(base64.b64decode(item, validate=False))
        return str(output)
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


def strip_error_body(body: str) -> str:
    body = re.sub(r"<(script|style).*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<.*?>", " ", body, flags=re.S)
    body = html.unescape(re.sub(r"\s+", " ", body)).strip()
    return body[:700] or "No provider error body."


def hosted_ace(ace_base: str, ace_key: str, payload: dict[str, Any]):
    """Stream ACE /v1/chat/completions with SSE heartbeats to avoid Cloudflare timeouts.

    Yields (heartbeats, elapsed_seconds, lm_content, audio_file) tuples:
      - heartbeats       : count of "." heartbeat chunks received
      - elapsed_seconds  : wall-clock seconds since stream started
      - lm_content       : accumulated response text metadata
      - audio_file       : None for progress yields; local filepath on final yield
    Raises gr.Error on unrecoverable failures.
    """
    url = f"{base_url(ace_base)}/v1/chat/completions"

    def _run_stream(current_payload: dict[str, Any]):
        """Inner generator for SSE parsing."""
        heartbeats = 0
        lm_content = ""
        start = time.time()

        try:
            with httpx.stream(
                "POST",
                url,
                headers=headers(required(ace_key, "ACE API key")),
                json=current_payload,
                # connect=30s is plenty for TCP. write=60s allows large payloads.
                # read=120s must cover the time before the first SSE chunk arrives,
                # plus any gaps between heartbeats (heartbeats are every ~2s once
                # generation starts, so this is ~60x headroom).
                timeout=httpx.Timeout(connect=30.0, read=120.0, write=60.0, pool=10.0),
            ) as resp:
                if resp.status_code >= 400:
                    body = strip_error_body(resp.text)
                    if resp.status_code == 504:
                        body = f"{body} The hosted ACE gateway timed out. Try a shorter duration if you want to reduce runtime/cost."
                    raise gr.Error(f"ACE hosted request failed: HTTP {resp.status_code}. {body}")

                for raw_line in resp.iter_lines():
                    if not raw_line or not raw_line.startswith("data: "):
                        continue
                    if raw_line == "data: [DONE]":
                        break

                    try:
                        chunk = json.loads(raw_line[6:])
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    finish_reason = choices[0].get("finish_reason")

                    if finish_reason == "error":
                        err_text = delta.get("content") or "ACE generation failed."
                        raise gr.Error(f"ACE stream error: {err_text}")

                    # Handle heartbeats (keep connection alive)
                    content = delta.get("content")
                    if content == ".":
                        heartbeats += 1
                        yield heartbeats, time.time() - start, lm_content, None
                    elif content:
                        lm_content += content
                        yield heartbeats, time.time() - start, lm_content, None

                    # Extract audio from stream
                    audio_parts = delta.get("audio") or []
                    if audio_parts:
                        audio_url_str = (audio_parts[0].get("audio_url") or {}).get("url", "")
                        if audio_url_str:
                            audio_file = save_audio_item(ace_base, audio_url_str)
                            yield heartbeats, time.time() - start, lm_content, audio_file
                            return

        except gr.Error:
            raise
        except Exception as exc:
            raise gr.Error(redact(f"ACE stream failed: {exc}", ace_key)) from exc

        raise gr.Error("ACE hosted stream ended without returning audio.")

    # --- Main retry loop -----
    tried_without_ref_audio = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            yield from _run_stream(payload)
            return
        except gr.Error as exc:
            exc_str = str(exc)
            is_transient = (
                "timeout" in exc_str.lower()
                or "connection" in exc_str.lower()
                or "disconnected" in exc_str.lower()
            )

            # If reference audio is in payload and error is transient, try without it
            if is_transient and not tried_without_ref_audio:
                has_ref_audio = False
                messages = payload.get("messages") or []
                for msg in messages:
                    content = msg.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if block.get("type") == "input_audio":
                                has_ref_audio = True
                                break

                if has_ref_audio:
                    tried_without_ref_audio = True
                    # Remove reference audio and reference-specific fields from payload
                    new_payload = json.loads(json.dumps(payload))
                    for msg in new_payload.get("messages") or []:
                        content = msg.get("content")
                        if isinstance(content, list):
                            msg["content"] = [b for b in content if b.get("type") != "input_audio"]
                    new_payload.pop("task_type", None)
                    new_payload.pop("instruction", None)
                    new_payload.pop("audio_cover_strength", None)
                    new_payload["thinking"] = True
                    new_payload["use_format"] = True
                    new_payload["use_cot_caption"] = True
                    new_payload["use_cot_language"] = True
                    yield -1, 0.0, "_Reference audio caused a disconnect — retrying without it…_", None
                    payload = new_payload
                    continue

            # Transient error without ref audio → back off and retry
            if is_transient and attempt < MAX_RETRIES:
                yield -1, 0.0, f"_Connection error — retrying ({attempt}/{MAX_RETRIES - 1})…_", None
                time.sleep(RETRY_BACKOFF * attempt)
                continue

            raise


def native_ace(ace_base: str, ace_key: str, candidate: dict[str, Any], ace_model: str) -> str:
    is_instrumental = candidate_is_instrumental(candidate)
    payload = {
        "prompt": candidate["prompt"],
        "lyrics": "" if is_instrumental else candidate["lyrics"],
        "bpm": candidate["bpm"],
        "key_scale": candidate["key_scale"],
        "time_signature": candidate["time_signature"],
        "audio_duration": candidate["audio_duration"],
        "vocal_language": candidate["vocal_language"],
        "is_instrumental": is_instrumental,
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
    if candidate.get("needs_reference_search") and not ref_audio:
        raise gr.Error(
            "This is a source-edit/cover task, so ACE needs real reference audio to keep the original song. "
            "Automatic search did not find a usable direct preview/audio file, so I stopped instead of rendering a different text-only song. "
            "Try a prompt with the exact song title and artist, or include a direct mp3/m4a/wav URL in the prompt."
        )
    if candidate.get("needs_reference_search") and ref_audio:
        ref_duration = ref_audio.get("duration")
        requested_duration = candidate.get("audio_duration", 0)
        if (
            isinstance(ref_duration, (int, float))
            and ref_duration < 60
            and requested_duration > ref_duration + 10
        ):
            raise gr.Error(
                f"The automatic reference is only {ref_duration:.1f}s, but the selected candidate asks for "
                f"{requested_duration}s. This is probably a preview clip, not the full song, so ACE can only make "
                "a short or incomplete cover from it. I stopped instead of rendering another 30-second result. "
                "Use a prompt with a direct authorized full-song mp3/m4a/wav URL, or lower the candidate duration."
            )

    payload = ace_payload(candidate, ace_model or "", ref_audio)
    log = ["## ACE progress / render log", ref_log, "```json", json.dumps(redact_audio(payload), indent=2), "```"]
    yield "\n".join(part for part in log if part), None

    try:
        if (urlparse(base_url(ace_base)).hostname or "").lower() == "api.acemusic.ai":
            # Stream from hosted ACE with SSE heartbeats
            log.append("Connecting to ACE…")
            yield "\n".join(log), None
            
            lm_content = ""
            audio_file = None
            for heartbeats, elapsed, lm_text, af in hosted_ace(ace_base, ace_key, payload):
                lm_content = lm_text
                if af is None:
                    # heartbeats < 0 means retry message, show as log line
                    if heartbeats < 0:
                        log.append(lm_text)
                    else:
                        # Progress update — show heartbeat counter
                        log[-1] = f"Generating… {heartbeats} heartbeat(s) ({elapsed:.0f}s elapsed)"
                    yield "\n".join(log), None
                else:
                    # Final yield with audio
                    audio_file = af

            log[-1] = "Created audio via hosted ACE."
            if lm_content.strip() and not lm_content.startswith("_"):
                log.append(lm_content[:1200])
            log.append(f"Saved: `{audio_file}`")
            yield "\n".join(log), audio_file
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
