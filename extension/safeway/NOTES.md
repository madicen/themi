# Safeway: what the site does (prompt 35b spike)

Recorded 2026-10-31 from safeway.com's own scripts, signed out, store 3132 (Oakland,
Broadway). The site changes; re-check before trusting any of this.

## Page globals

- `window.AB.userInfo.branchId`: the selected store ID (used as `storeid`).
- `window.AB.userInfo.SWY_SHOP_TOKEN`, `clubCard`, `zipcode`, `registered`: the signed-in
  session. `isAuthorized` gates the site's own add-to-cart button.
- Sign-in is Albertsons CIAM (`ciam.albertsons.com`, Okta); the page refreshes it with
  `/api/v1/sessions/me/lifecycle/refresh`.

## Bot protection

Akamai Bot Manager: the page posts sensor data to an odd same-origin path
(`/Vnsane-to-done-…`, it changes). From Cursor's embedded browser every request worked
except product search, which failed at the network level ("Failed to fetch") for the site
itself as well as for a hand-made call. So the search endpoint is the guarded one, and an
automated browser gets cut off there. Untested in the family's real Chrome.

## Product search

`GET /abs/pub/xapi/pgmsearch/v1/search/products` with query parameters `request-id`
(random digits), `url` and `pageurl` (the site origin), `pagename=search`, `rows`, `start`,
`search-type=keyword`, `storeid`, `featured`, `q`, `sort`, `timezone`, `dvid=web-4.1search`,
`channel` (`pickup` or `delivery`, from the user's preference cookie), and `pp=true` when
signed in. Header `Ocp-Apim-Subscription-Key`: a public key embedded in the site's config
(`searchProductsAPIDetails` in `clientlib-angular-global`). Don't hardcode it; keys rotate.

Response shape: not yet captured (blocked here).

## Cart

- Config `cartAPIDetails` in `clientlib-angular-global`: `cartAPI` `/abs/pub/erums/cartservice/api/v1/cart/`,
  `cartV2API` `/abs/pub/erums/cartservice/api/v2/cart/`, each with its own subscription key;
  guest carts at `/erums/guestcartservice/api/v2/guest/`. Items are posted to
  `…/cart/items?serviceType=…&storeId=…&zipCode=…`.
- The site's add button is `#addButton_<product id>` (quantity input `data-qty-id="pc<id>Inpt"`),
  shown only when signed in; signed out, it asks you to sign in.

Request body and auth headers: not yet captured (needs a signed-in session).

## Still needed, from a real signed-in Chrome

1. A search for "eggs": the request URL and headers, and the response body.
2. Adding one product to the cart: the request URL, headers (auth header names only) and
   body, and the response.

Save the responses in `fixtures/` with names, addresses, card numbers and tokens removed.
