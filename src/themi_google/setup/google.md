# Connect Google

Gmail, Google Calendar, Google Tasks and the family cookbook all go through a Google Cloud
project of your own. It's free, and takes about 15 minutes, once.

1. **Make a project.** At [console.cloud.google.com](https://console.cloud.google.com),
   make a new project, for example "Themi Household".
2. **Turn on the APIs.** Under **APIs & Services**, then **Library**, turn on the **Gmail
   API**, **Google Calendar API** and **Google Tasks API**. For the cookbook, also the
   **Google Docs API**, **Google Drive API** and **Google Picker API**.
3. **Name the app.** Under **Google Auth Platform**, then **Branding**, call it "Themi" and
   give a support email. Under **Audience**, choose **External**.
4. **Publish it, unverified.** Under **Audience**, press **Publish app** and don't ask for
   verification. People will see an "unverified app" warning when they link; **Advanced**,
   then **Go to Themi**, carries on. (Left in Testing, Google signs everyone out of Gmail
   every 7 days.)
5. **Make the client.** Under **Clients**, make an OAuth client of type **Web
   application**. Add this redirect address: `$SITE/auth/google/callback`
6. **Copy it here.** Paste the **client ID** and **client secret** into the boxes on this
   page and save.

## For the cookbook

Themi can open only a cookbook doc someone picks in Google's file picker. The picker needs
two more things, under the advanced settings:

- An **API key** limited to the Google Picker API (**APIs & Services**, then
  **Credentials**).
- The project **number**, from the project's dashboard.

Also add `$SITE` as an **Authorized JavaScript origin** on the OAuth client.

## After the restart

Each person links their Google account on [Accounts](/accounts). An admin enters each
person's Google address on the [Family page](/family), so they can sign in with Google too.
