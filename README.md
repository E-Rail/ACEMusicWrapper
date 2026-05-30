# ACEMusicWrapper

A local Gradio composer for ACE-Step style music generation.

The app has two layers:

- LLM composer layer: uses fast Bing search snippets and an OpenAI-compatible chat model to create several structured music samples and small-edit instructions.
- ACE render layer: sends one selected sample to the ACE API, saves the returned audio, and plays it in the UI.

API keys are entered in masked UI fields or loaded from `.env`. They are not written to logs, Markdown output, or saved files.

## Setup

Create the requested Conda environment:

```bash
conda create -n ACE python=3.11
conda activate ACE
pip install -r requirements.txt
```

Optionally create a local `.env` file:

```bash
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=your_llm_key_here
ACE_API_BASE=https://your-ace-api-base
ACE_API_KEY=your_ace_key_here
```

Do not commit `.env`. You can also leave `.env` empty and paste keys into the Gradio UI.

## Run

```bash
conda activate ACE
python app.py
```

Open the local Gradio URL printed in the terminal. The app launches with `share=False`.

## UI

- Top left: LLM and ACE base URLs plus masked API keys.
- Left bottom: prompt, LLM model dropdown, ACE model dropdown, selected sample dropdown, and action buttons.
- Top right: 3 tabbed LLM music candidates.
- Bottom right: ACE progress / render log, saved audio path, and playable final music.

## Workflow

1. Enter the LLM base URL/API key and ACE base URL/API key.
2. Click **Fetch models**.
   - All LLM provider models are shown.
   - `deepseek/deepseek-v4-flash (Suggested)` is selected by default when available.
3. Enter a music prompt, for example:

```text
J-pop rock, emotional vocal, 150 BPM, A minor, anime opening energy,
with a dramatic chorus and a short bridge for a later inpaint edit.
```

4. Click **Generate LLM samples**.
5. Pick one sample from **Selected LLM sample**.
6. Click **Render selected sample with ACE**.

The LLM returns structured candidates containing section-tagged lyrics:

```text
[Intro]
...

[Verse 1]
...

[Chorus]
...

[Bridge]
...

[Outro]
...
```

The ACE layer automatically chooses the right backend flow:

- Official cloud API at `https://api.acemusic.ai`: uses OpenRouter-compatible non-streaming `POST /v1/chat/completions`, waits for the full response, then decodes the returned base64 audio. For source-edit prompts, the app automatically tries to find an official/direct preview reference and attaches it as `input_audio` when available.
- Local/self-hosted ACE-Step API: uses native async endpoints, first `POST /v1/music/generate` then `GET /v1/jobs/{job_id}`, with legacy `/release_task` + `/query_result` fallback.

Generated audio is saved into `outputs/` and displayed in the audio player.

For source-edit tasks such as cover, repaint, extract, lego/add-layer, and complete,
the app decides whether reference search is needed. The LLM does not choose that flag
or provide reference URLs. The app searches automatically using direct prompt URLs,
Apple previews, and wider Bing queries including Chinese music terms/sites.
For Chinese edit prompts such as `孤勇者改成钢琴曲`, the app extracts `孤勇者`
as the source song and `钢琴曲` as the requested arrangement, then gives the LLM
source-focused Bing snippets so it does not invent an unrelated song.

## Provider Assumptions

- LLM provider is OpenAI-compatible for:
  - `GET {LLM_API_BASE}/models`
  - `POST {LLM_API_BASE}/chat/completions`
- Online search is app-side through Bing HTML search; the LLM provider does not need native web search tools.
- ACE provider supports one of:
  - official hosted flow: `POST {ACE_API_BASE}/v1/chat/completions`
  - native v1 flow: `POST {ACE_API_BASE}/v1/music/generate` then `GET {ACE_API_BASE}/v1/jobs/{job_id}`
  - legacy flow fallback: `POST {ACE_API_BASE}/release_task` then `POST {ACE_API_BASE}/query_result`
- ACE model fetching tries:
  - `GET {ACE_API_BASE}/v1/models`
  - `GET {ACE_API_BASE}/models`
  - If both fail, the app falls back to `default` and omits the model field.
- If your ACE base URL is `https://api.acemusic.ai`, the app uses `/v1/chat/completions` and requires a valid hosted ACE key. If `Fetch models` shows an auth error, create or refresh the key at `https://acemusic.ai/api-key`.
