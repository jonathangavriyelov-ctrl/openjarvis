# Build Your Own Jarvis

You don't need to train a model to get a personal Jarvis. You connect the right
pieces: a machine that stays on, an agent harness, a model you can swap, a
profile of who you are, long-term memory, skills, your tools, your messaging
channels and a voice. Then you add an interface.

OpenJarvis provides every one of those pieces, and the `personal-jarvis` preset
connects them:

```bash
jarvis init --preset personal-jarvis --force
```

The nine steps below explain each part of that preset and what to change.

| Step | Piece | In OpenJarvis |
|------|-------|---------------|
| 1 | A home | `jarvis serve` as a systemd / launchd service |
| 2 | Agent harness | OpenJarvis `orchestrator` agent + tools |
| 3 | The brain | `cloud` engine: Claude, GPT/Codex, Gemini (or local via Ollama) |
| 4 | Who you are | `SOUL.md`, `USER.md`, `MEMORY.md` |
| 5 | Long-term memory | `[memory]` with `backend = "honcho"` or `"local"` |
| 6 | Skills | `[[skills.sources]]` with Hermes Agent skills |
| 7 | Your tools | `jarvis connect`: Gmail, Calendar, Drive, browser |
| 8 | Channels + voice | Telegram, Slack, iMessage; ElevenLabs TTS |
| 9 | The Jarvis look | Your own UI on top of `/v1/chat/completions` + `/v1/speech/*` |

---

## 1. Give it a home

Jarvis needs a machine that is always on: an old laptop, a Mac mini, or a
small cloud server. Install OpenJarvis there, then run the server as a service
so it restarts on boot and after crashes:

```bash
curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash

# Linux
sudo cp deploy/systemd/openjarvis.service /etc/systemd/system/
sudo systemctl enable --now openjarvis

# macOS
cp deploy/launchd/com.openjarvis.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.openjarvis.plist
```

Keep the server on `127.0.0.1` and set `OPENJARVIS_API_KEY`. To reach it from
your phone, use `jarvis tunnel` instead of exposing the port directly.

## 2. Install the agent harness

The harness turns a model into an agent that can do work: it runs the
tool-calling loop, manages context and enforces permissions. In OpenJarvis
this is the `orchestrator` agent, set in the preset:

```toml
[agent]
default_agent = "orchestrator"
max_turns = 15
```

`[tools] enabled` is the complete list of what the agent may do. Nothing else
is granted.

## 3. Pick the brain

You're not tied to one model. The `cloud` engine talks to Anthropic, OpenAI
and Google directly. Set the key for the provider you want and choose a model:

```toml
[engine]
default = "cloud"

[intelligence]
default_model = "claude-sonnet-4-6"   # or "gpt-5", "gemini-3-pro"
```

To switch for one session, run `jarvis chat --model gemini-3-pro`. To keep
everything on your own hardware, set `default = "ollama"` and choose a local
model.

## 4. Teach it who you are

Three Markdown files in `~/.openjarvis/` are added to every prompt:

- **`SOUL.md`**: how Jarvis behaves (tone, how it addresses you, what it must
  never do).
- **`USER.md`**: who you are: your work, goals, people, preferences, and how
  you like things done.
- **`MEMORY.md`**: running notes the agent keeps for itself.

`jarvis` creates these files on first run. Write `USER.md` yourself: a
few honest paragraphs help more than any other setting. The
`user_profile_manage` tool lets Jarvis add to the file as it learns.

## 5. Give it long-term memory

With `[memory] enabled = true`, a background service pulls lasting facts out
of every conversation, such as "prefers morning meetings" or "manager is
Priya". It then feeds relevant facts back into later prompts.

```toml
[memory]
enabled = true
backend = "honcho"     # or "local"
```

- **`local`** keeps facts in `~/.openjarvis/memory_facts.jsonl`.
- **`honcho`** keeps the same local file and also sends each fact to
  [Honcho](https://honcho.dev). Honcho builds a model of you across sessions.
  Set `HONCHO_API_KEY`, or set `HONCHO_URL` for a self-hosted Honcho, and
  install the SDK with `uv pip install honcho-ai`. Facts that the injection
  scanner quarantined are never sent. If Honcho is unreachable, local memory
  keeps working.

Review what Jarvis has learned with `jarvis memory list`, and delete it with
`jarvis memory clear`.

## 6. Add skills

Skills are short guides for specific jobs, such as triaging an inbox or
preparing a meeting brief. The preset imports skills from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research:

```toml
[[skills.sources]]
source = "hermes"
filter = { category = ["productivity", "research", "email"] }
```

Add more with `jarvis skill install hermes:<name>`, or import any GitHub repo
that follows the [agentskills.io](https://agentskills.io/specification)
standard.

## 7. Connect your tools

```bash
jarvis connect gdrive              # one OAuth sign-in covers Gmail, Calendar, Drive, Tasks
jarvis memory index ~/Documents    # make your documents searchable
```

The preset enables the email, calendar, document search, browser and
scheduler tools. `schedule_task` lets Jarvis set up its own recurring jobs,
for example "every weekday at 8am, summarise my inbox". Other connectors
(Notion, Obsidian, Outlook, Slack, Apple Notes and more) are listed in
[Channels & Connectors](channels-and-connectors.md).

## 8. Connect your channels and give it a voice

**Messaging.** Export `TELEGRAM_BOT_TOKEN` (or `SLACK_BOT_TOKEN` +
`SLACK_APP_TOKEN`) and set `[channel.telegram] allowed_chat_ids` so that only
you can talk to the bot. For iMessage on a Mac, run
`jarvis channels imessage-start`, or use the BlueBubbles bridge. See
[Channels](channels.md).

**Voice.** Export `ELEVENLABS_API_KEY`. The preset uses ElevenLabs'
"George", a warm British voice, for the movie feel. Replace `voice_id` with
any voice from your ElevenLabs library:

```toml
[speech]
tts_backend = "elevenlabs"
voice_id = "JBFqnCBsd6RMkjVDRZzb"
```

`jarvis chat --voice` lets you talk to it from the terminal. Set
`ELEVENLABS_MODEL` to change the model, e.g. `eleven_flash_v2_5` for lower
latency.

## 9. The Jarvis look

Design the interface in any tool you like, such as Claude Design or Figma. It
then needs three endpoints from `jarvis serve`:

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/speech/transcribe` | microphone audio → text |
| `POST /v1/chat/completions` | text → Jarvis's reply (OpenAI-compatible) |
| `POST /v1/speech/synthesize` | reply → audio in Jarvis's voice |

`/v1/speech/synthesize` takes `{"text": "..."}` and returns audio (`audio/mpeg`
by default). It uses the voice from `[speech]` unless the request sets
`backend` or `voice_id`. This is all the code needed to connect the voice to
your UI:

```js
const API = "http://127.0.0.1:8000";
const headers = { Authorization: `Bearer ${OPENJARVIS_API_KEY}` };

async function askJarvis(text) {
  const chat = await fetch(`${API}/v1/chat/completions`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",   // same model as [intelligence] default_model
      messages: [{ role: "user", content: text }],
    }),
  }).then((r) => r.json());
  const reply = chat.choices[0].message.content;

  const audio = await fetch(`${API}/v1/speech/synthesize`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ text: reply }),
  }).then((r) => r.blob());
  new Audio(URL.createObjectURL(audio)).play();   // animate your orb here
  return reply;
}
```

Result: an agent that knows you, uses your tools, reaches you where you
are, and talks back.

## Privacy checklist

This setup sends data to cloud providers: prompts to your model provider,
memory facts to Honcho, and spoken replies to ElevenLabs. Run
`jarvis scan --data-boundaries` to list each of these paths. For a
local-only setup, use Ollama, `backend = "local"` and
`tts_backend = "kokoro"`.
