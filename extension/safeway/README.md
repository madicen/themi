# Themi Safeway helper

A Chrome extension that fills your Safeway cart from a list, using the Safeway sign-in you
already have in Chrome. It only adds to the cart: you check out on safeway.com yourself. It
never touches checkout, payment, delivery times or addresses, and it never removes anything.

## Install (once per computer)

1. In Chrome, open `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this folder (`extension/safeway` in the Themi repo).
4. Pin it: click the puzzle-piece icon in the toolbar, then the pin next to
   "Themi Safeway helper".

After pulling a new version, click the reload arrow on its card in `chrome://extensions`, then
reload any open safeway.com tabs.

## Use

1. Open safeway.com in a tab and sign in. Pick delivery or pickup and your store as usual.
2. Click the extension's icon and type the list, one item per line. A number in front sets
   how many: `2 oat milk`.
3. Click **Fill cart**. It goes one item at a time with a short pause, so a long list takes
   a minute. You can close the popup; it keeps going in the Safeway tab.
4. The popup lists what it added (name, size, price), what was out of stock and what it
   couldn't find. Check the cart on safeway.com and check out when you're ready.

The first time it fills "eggs" it takes the top search result and remembers it, so next time
"eggs" is the same product. If it picked the wrong one, click **change** next to it and
choose another: that one is added and remembered. The first one stays in the cart, so remove
it on safeway.com.

If it says **"Sign in to Safeway, then try again."**, your Safeway sign-in has expired or
Safeway wanted a check that the extension can't do. Sign in again in the tab (or reload it)
and click **Fill cart** again. Anything already added stays in the cart and is added on top.

## Connect it to Themi (optional)

Then "fill the Safeway cart" in Themi's chat fills it here, and both of your browsers
remember the same products.

1. On Themi's website, open **Safeway** and click **Connect the Safeway helper**. Copy the
   token it shows (it's shown only once).
2. Right-click the extension's icon, choose **Options**, and enter Themi's address (the
   website's address, `https://...`) and the token. Click **Connect** and allow access to
   that address when Chrome asks.
3. Say "fill the Safeway cart" to Themi and answer **Go ahead**. The next time a safeway.com
   tab is open (signed in), the helper fills the cart within a minute and Themi messages you
   what it added. If no tab is open within 2 hours, Themi sends the list with Safeway links
   instead.

Each browser gets its own token, and either can be disconnected on Themi's Safeway page.
That page also shows the remembered products: change what to search for, or forget one.

## For developers

- `lib/` holds the logic (list parsing, the Safeway calls, the fill, talking to Themi, the
  worker's polling), shared by the content script, the service worker, the popup and the
  tests. `background.js` is the service worker: it polls Themi while a Safeway tab is open.
  `page.js` runs in the page's own world to read the store, sign-in token and API keys from
  safeway.com's globals.
- [NOTES.md](NOTES.md) records the requests and how they were found. Safeway changes its
  site; when something breaks, start there.
- Tests: `node --test extension/safeway/tests/*.test.js`, also run by `make test-all`. They use
  the saved responses in `fixtures/` and make no network calls.
