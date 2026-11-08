# The dishwasher, through Home Connect

A Bosch, Siemens or other Home Connect dishwasher can tell Themi when it runs. Themi only
reads it; it never controls it.

1. At [developer.home-connect.com](https://developer.home-connect.com), make a free
   developer account and register an application.
2. Choose the **Authorization Code Grant Flow**, and add this redirect address:
   `$SITE/auth/home-connect/callback`
3. Paste the app's **client ID** and **client secret** here and save.

## After the restart

An admin links Home Connect on [Accounts](/accounts). The dishwasher then shows under
Appliances.
