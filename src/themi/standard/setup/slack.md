# Set up Themi's Slack app

Themi joins your company's Slack as a custom app, and each person talks to it in a direct
message. It connects over Socket Mode, so Themi needs no public address.

## Before you start

- Ask a Slack workspace admin (and IT or security, if they review apps) to approve a custom
  app named Themi. Tell them what it can do: direct messages only, with the people who
  write to it; no channel access; it reads the DMs sent to it, posts replies, reactions and
  files there, reads names and emails to pair people, and sets your own Slack status and Do
  Not Disturb (with your user token).
- Say where it runs and what it connects to: a Themi you host, holding outbound
  connections to Slack only, plus your work email and calendar and the AI provider it uses.
- On an Enterprise Grid org, an org admin may need to approve it for the workspace too.

## Create and install the app

1. Go to [api.slack.com/apps](https://api.slack.com/apps), choose **Create New App**, then
   **From an app manifest**, and pick your workspace.
2. Paste the manifest below, check the summary, and choose **Create**.
3. Under **Basic Information**, **App-Level Tokens**, choose **Generate Token and Scopes**,
   name it `themi-socket`, add the `connections:write` scope, and copy the `xapp-` token.
4. Under **Install App**, choose **Install to Workspace** (or **Request to Install** when
   your workspace needs approval: an admin approves it in **Manage apps**, then you come
   back and install).
5. Under **OAuth & Permissions**, copy the **Bot User OAuth Token** (`xoxb-`), and the
   **User OAuth Token** (`xoxp-`) if you want status sync.
6. Paste the tokens here, save, and press **Test**. It says which token didn't work, if
   one doesn't.

With the user token, Themi shows **Focusing** and turns on Do Not Disturb while a block it
put on your calendar for a task is on, shows **In a meeting** during meetings, and turns on
Do Not Disturb in your quiet hours. It never reads your status, and leaves one you set
yourself alone. Without the user token, everything else works.

```
display_information:
  name: Themi
  description: A personal work assistant
features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: Themi
    always_online: true
  slash_commands:
    - command: /themi
      description: Run a Themi command
      usage_hint: pause | site
      should_escape: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - im:history
      - im:read
      - im:write
      - users:read
      - users:read.email
      - reactions:read
      - reactions:write
      - files:read
      - files:write
      - commands
    user:
      - users.profile:write
      - dnd:write
settings:
  event_subscriptions:
    bot_events:
      - message.im
      - reaction_added
      - reaction_removed
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

## After the restart

In Slack, find Themi under **Apps** in the sidebar, open its **Messages** tab and say
hello. Themi pairs you by your Slack email when it's your email in Themi too; otherwise
send the code from the [Family page](/family). Commands are `/themi pause`, `/themi site`
and the rest: `/themi` alone lists them.

Keep the tokens private. If one leaks, make a new one on the same page (the bot token by
reinstalling the app) and paste it here.
