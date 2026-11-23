# The Safeway cart, filled by the helper

The Safeway helper is a Chrome extension that fills the Safeway cart for you, using the
Safeway sign-in you already have in Chrome. Its popup shows the grocery list, and "fill the
Safeway cart" in chat fills it too. It only ever adds to the cart: you check out on
safeway.com yourself. Each computer that shops needs it installed once.

## Install it in Chrome

1. Download Themi: [themi-main.zip](https://github.com/madicen/themi/archive/refs/heads/main.zip).
   Unzip it somewhere it can stay, such as Documents. Chrome loads the helper from that
   folder each time, so don't delete it.
2. In Chrome, open `chrome://extensions` (type it into the address bar).
3. Turn on **Developer mode**, top right.
4. Click **Load unpacked** and choose the `extension/safeway` folder inside the unzipped
   `themi-main` folder.
5. Pin it: click the puzzle-piece icon in Chrome's toolbar, then the pin next to **Themi
   Safeway helper**. Its icon is the chameleon with a cart.

## Connect it to Themi

1. On the [Safeway page](/safeway), click **Connect the Safeway helper** and copy the token
   it shows. It's shown only once.
2. Right-click the helper's icon and choose **Options**.
3. For Themi's address enter `$SITE`, paste the token, and click **Connect**. Allow access
   to that address when Chrome asks.

The popup then says **Connected to Themi** and lists the grocery list. Each browser gets its
own token, and any of them can be disconnected on the [Safeway page](/safeway).

## Using it

Open safeway.com in a tab and sign in (the popup's **Open Safeway** does it), with delivery
or pickup and your store picked as usual. Then untick anything you don't want in the popup
and click **Add to cart**. When you ask Themi to fill the cart instead, the helper does it
within a minute of a signed-in Safeway tab being open. If none is open within 2 hours, Themi
sends the list with Safeway links.

## Updating it

When a new version comes, download and unzip it again over the same folder. Then click the
reload arrow on the helper's card in `chrome://extensions`, and reload any open Safeway
tabs. If the popup offers **Reload tab**, that's all it needs.
