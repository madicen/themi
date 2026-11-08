# Groceries said to Google Home

"Hey Google, add tomatoes to my shopping list" puts them in Google Keep. With this on,
Themi brings them into the grocery list, and keeps Keep in step.

Google doesn't open Keep to personal accounts, so this uses an unofficial library and a
token that can do nearly anything to its Google account. Themi keeps it encrypted and uses
it only for Keep.

## After the restart

Linking is done on the server, for now: for each person, run `themi keep link <name>` and
follow its steps.
