# Personal desk: Google and your phone

The personal desk is the Chief of Staff page. Two connections make it useful
away from the laptop: Google, so the Executive Assistant can see the day, and
a phone channel, so you can message the chief and get the answer back in that
same chat.

Neither connection is required. If Google is not connected, the briefing is
empty and the rest of the desk still works. If the phone is not configured,
it stays off.

## What the agents are allowed to do

The Executive Assistant can **read** Gmail and Google Calendar. That shows up
as the daily briefing: inbox, priorities, and upcoming meetings.

The Second Brain can **read** Google Drive documents and save matching docs
as notes.

They do not send email. They do not create, move, or edit calendar events on
their own. If you ask for an email or a meeting, the chief files a **draft**
on the Chief of Staff page. Nothing leaves your account until you press
**Approve**. **Reject** throws the draft away and does not call Google.

If the Google token is read-only, Approve still marks the draft approved and
tells you to copy it yourself. The desk will not pretend the message was sent.

## Connect Google

You use your own OAuth client. Put the secrets in the environment or in the
OpenJarvis home directory (`~/.openjarvis`). Do not commit them, and do not
paste them into the repository.

### 1. Create a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/) and sign in
   with the Google account whose mail, calendar, and Drive you want to read.
2. Create a project (or pick one you already use for OpenJarvis).

### 2. Turn on the three APIs

In **APIs & Services → Library**, enable:

- Gmail API
- Google Calendar API
- Google Drive API

### 3. Set the consent screen

1. Open **APIs & Services → OAuth consent screen**.
2. Choose **External** if this is a personal Gmail account. An internal
   screen only works for a Google Workspace organization.
3. Fill in the app name (anything you will recognize, such as "Personal desk").
4. Add your own Gmail address as a **test user**. While the app is in testing,
   Google only lets those users through.

### 4. Create the OAuth client

1. Open **APIs & Services → Credentials**.
2. **Create credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Copy the **Client ID** and **Client secret**. Leave them out of git.
5. If Google asks for a redirect URI, add `http://localhost:8789/callback`.
   That is the address the existing OpenJarvis connect command listens on.

### 5. Sign in once

The simplest path reuses the connector OpenJarvis already has. From the repo:

```bash
uv run jarvis connect gmail
```

Paste the client id and secret when it asks. A browser opens. Sign in as
yourself and allow access. The command writes tokens under
`~/.openjarvis/connectors/` (including `google.json`). The personal desk
reads that file. You do not copy it into the project.

`jarvis connect gdrive` or `jarvis connect gcalendar` is the same Google
login. One successful consent covers Gmail, Calendar, and Drive.

### 6. Or set environment variables

If you already have a refresh token (it is inside `google.json` after the
connect command), you can point the desk at it without a second login:

```bash
export GOOGLE_CREDENTIALS_PATH="$HOME/.openjarvis/connectors/google.json"
```

Or, without pointing at a file:

```bash
export GOOGLE_CLIENT_ID="your-client-id"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export GOOGLE_REFRESH_TOKEN="your-refresh-token"
```

The desk writes those three values next to its own database, under the
OpenJarvis home, not into the git checkout.

Config file equivalent, still without the secret itself:

```toml
[personal]
google_credentials_path = ""  # prefer the env var above
```

### Scopes, and why Approve can still fail

The shared OpenJarvis Google login asks for Gmail modify and full Calendar
so other OpenJarvis tools can archive mail or respond to invites **after a
person approves**. The personal desk does not use those write calls unless
you press Approve.

If you want even Approve to be unable to send, create the token with
read-only scopes only:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/calendar.readonly`
- `https://www.googleapis.com/auth/drive.readonly`

Reading still works. Approve keeps the draft and says the token cannot send.

Restart the OpenJarvis server after you set the variables. The Chief of Staff
page then shows the inbox and upcoming meetings. On the Second Brain page,
**Pull from Drive** saves matching documents as notes. A mission that asks
the second brain to remember something also pulls matching Drive docs.

## Message the chief from your phone

Telegram is the one to set up. Slack works too, because a Slack channel
already lives in this repo. Both stay silent until **your** chat id or Slack
user id is set. A token alone is not enough: with an empty allow-list the
bridge does not start, and a message from anyone else is ignored.

### Telegram (preferred)

1. Install Telegram on your phone and open a chat with
   [@BotFather](https://t.me/BotFather).
2. Send `/newbot`.
3. Pick a display name and a username that ends in `bot`.
4. BotFather replies with a token that looks like `123456:ABC...`. That is
   the bot token. Keep it private.

```bash
export TELEGRAM_BOT_TOKEN="the-token-from-botfather"
```

5. In Telegram, open your new bot and send it any message, such as `hi`.
   A bot cannot see a chat until you start it.
6. Find your numeric chat id. In a browser, open:

   `https://api.telegram.org/bot<your-token>/getUpdates`

   Look for `"chat":{"id":123456789`. That number is your chat id. You can
   instead message [@userinfobot](https://t.me/userinfobot) and read the id
   it shows you.

```bash
export TELEGRAM_CHAT_ID="123456789"
```

7. Install the Telegram library the channel uses, then start the server as
   usual:

```bash
pip install python-telegram-bot
```

If that package is missing, the desk still starts. The phone status line
says Telegram is off until the package is installed.

Message the bot from your phone. The reply comes back in that same chat.
A message from any other chat id is dropped.

You can put the chat id in config instead of the environment. The
environment wins when both are set. Prefer the environment for the token.

```toml
[personal]
telegram_chat_id = "123456789"

[channel.telegram]
allowed_chat_ids = "123456789"
```

Leave `bot_token` empty in the file and use `TELEGRAM_BOT_TOKEN`.

### Slack

Use this if you already talk to OpenJarvis in Slack. The setup for the Slack
app itself is the same as the Slack section of
[Channels & Connectors](channels-and-connectors.md): a bot token (`xoxb-...`)
and a Socket Mode app token (`xapp-...`).

Then restrict the desk to your Slack member id. In Slack, click your profile
and copy the member id (`U...`).

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_APP_TOKEN="xapp-..."
export SLACK_ALLOWED_USER_ID="U0123456789"
pip install slack-sdk
```

Or in config, again without putting the tokens in the file:

```toml
[personal]
slack_user_id = "U0123456789"

[channel.slack]
allowed_user_ids = "U0123456789"
```

Direct-message the bot. The answer is posted back to that same conversation.
Someone else's Slack user id cannot start a mission. If
`SLACK_ALLOWED_USER_ID` is empty, Slack does not listen, even when the bot
token is set.

## Worlds

A world is a separate space. Jonathan starts with **Personal** and one
business world, **Quick Funders**. Add, rename, or delete business worlds
from the eco world. Personal cannot be deleted.

Each world has its own:

- Google account or accounts (mail, calendar, and Drive for that world)
- projects, goals, notes, and deliverables
- agent team, including which model OmniRoute should use and whether that
  agent may call Higgsfield

Business mail stays in the business world. Personal agents do not read it.
The top-level Chief of Staff is the exception: that chief can see every
world, route a request when you name the world, and give one combined
daily briefing. On the phone, say the world name (for example "Quick
Funders") to land in that world. If you do not name one, the top-level
chief answers across worlds and does not mix the businesses into one
specialist task.

### More than one Google account

`jarvis connect gmail` still signs in one account and writes one credentials
file. For a second account, run the connect flow again (or use a second
Desktop client) so you have a second JSON file **outside this repository**.
In the dashboard, open the world and assign that file with the account
email. The desk stores the file path, not the token, and API responses
never include the path or the secret.

The eco world draws each world as a planet around the top-level chief.
Click a planet to zoom into that world's projects, goals, and agents.

## What you should see

- **Chief of Staff**: an inbox and meetings card (one world, or a combined
  card when All worlds is selected), a phone line for Telegram and Slack,
  and any email or calendar drafts with Approve and Reject.
- **Second Brain**: Pull from Drive inside a world, then the saved notes.
  From All worlds the page asks you to open a world first.
- **Eco world**: planets for Personal, Quick Funders, and any world you
  add. A line when Google is readable or Telegram is on.

The dashboard never shows the bot token, the OAuth client secret, or the
refresh token.
