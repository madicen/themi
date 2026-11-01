# Safeway: what the site does (prompt 35b spike)

First recorded 2026-10-31 from safeway.com's own scripts, signed out. Then checked the same
day in the family's real Chrome, signed in, through Claude in Chrome: every call below was
made with a plain `fetch` from the page (not the site's own code) and worked. The site
changes; re-check before trusting any of this.

Result: direct calls work. The extension doesn't need to click the site's buttons.

## Page globals the extension reads (never hardcoded)

| What | Where | Notes |
| --- | --- | --- |
| Store ID | `AB.userInfo.branchId` | `storeid` / `storeId` |
| Banner | `AB.userInfo.banner` | `safeway` |
| ZIP code | `AB.userInfo.zipcode` | cart calls only |
| Channel | `AB.COMMON.getUserChannel()` | `delivery` or `pickup` |
| Sign-in token | `AB.userInfo.SWY_SHOP_TOKEN` | a JWT; empty when signed out. Not in a cookie or storage |
| Search key | `SWY.CONFIGSERVICE.searchConfig.apimProgramSubscriptionKey` | public APIM key |
| Cart key | `AB.cartapimkey` | also `SWY.CONFIGSERVICE.erumsConfig.cart.apim.key` |
| Cart ID | `localStorage.cartId` | JSON `{"abs": <number>}` |

`AB` and `SWY` are page globals, so the script that reads them must run in the page's MAIN
world (`"world": "MAIN"` in the manifest's content scripts). `localStorage` is shared with
the isolated world too.

Sign-in is Albertsons CIAM (`ciam.albertsons.com`, Okta); the page refreshes it with
`/api/v1/sessions/me/lifecycle/refresh`.

## Product search

`GET /abs/pub/xapi/pgmsearch/v1/search/products`, header `Ocp-Apim-Subscription-Key` (search
key) and `Accept: application/json`. No sign-in token. This minimal set of query parameters
works: `request-id`, `url` and `pageurl` (the origin), `pagename=search`, `rows`, `start`,
`search-type=keyword`, `storeid`, `featured=false`, `q`, `sort=` (empty),
`dvid=web-4.1search`, `channel`, `banner`, `pp=true`.

- `request-id` must be the site's format: 3 random digits, `Date.now()`, 3 random digits
  (`_getUTCTimeStampRandom`). Anything else still returns HTTP 200, but
  `primaryProducts.appCode` is `"400"` with "Search encountered a problem... OSSR0033-R"
  (`fixtures/search-bad-request-id.json`).
- `featured=true` (the site's default) puts sponsored products first: "bananas" led with a
  banana bread mix. With `featured=false` the first result was "Banana". Also skip any doc
  with `featured: true`.
- Results: `primaryProducts.response.docs[]`. Use `pid` (the product ID the cart takes),
  `name` (includes the size, "... - 18 Count"), `price`, `inventoryAvailable` (`"1"` in
  stock, `"0"` out of stock), `status` (`active`). Sizes are also in `dispItemSizeQty` /
  `dispUnitOfMeasure` or `itemSizeQty` / `unitOfMeasure`.
- No match: a nonsense query still returns about 30 unrelated products, with
  `response.isExactMatch: false` (`fixtures/search-no-match.json`). Treat that as not found.
- Seen in Akamai's place: from the real Chrome, nothing was blocked across about 20 searches
  at roughly one a second. The earlier "Failed to fetch" was the embedded browser.

## Cart

Add or set: `POST /abs/pub/erums/cartservice/api/v2/cart/items` with query parameters
`storeId`, `serviceType`, `zipCode`, `cartCategoryList=1P`. Headers `Content-Type:
application/json`, `Ocp-Apim-Subscription-Key` (cart key), `Authorization: Bearer
<SWY_SHOP_TOKEN>`. Body (`fixtures/cart-add-request.json`):

```json
{"cartItemsList":[{"itemId":"970597593","qty":1,"comments":"","isSnsSub":false}],"cartCategory":"abs"}
```

- `serviceType` is `Delivery`, `DUG` (pickup) or `inStore`; anything else is a 400
  (`fixtures/cart-bad-params-400.json`). `cartCategoryList` must be `1P`, `1P_WINE`,
  `1P_MTO` or `ALL`.
- **`qty` sets the quantity, it doesn't add.** Posting 2 then 1 for the same product left 1.
  So the extension reads the cart first and posts `current + wanted`, or it could lower a
  quantity someone already chose.
- The response is the whole cart (`fixtures/cart-add-response.json`): `carts[0].cartItemsList[]`
  with `itemId`, `name`, `qty`, `price`, `isOOS`, `isAvailable`.
- Signed out (no `Authorization`): 401 `{"developerMessage":"Not Authorized"}`. A bad or
  expired token: 403 `Forbidden`. Both mean "Sign in to Safeway, then try again."

Read: `GET /abs/pub/erums/cartservice/api/v2/cart/<cartId>` with the same query parameters
and headers returns one cart object (`fixtures/cart-get-response.json`, the same shape as
`carts[0]`). With no `cartId` in `localStorage` (a new cart), treat the cart as empty.

The site's own add button is `#addButton_<product id>`; it isn't needed.

Fixtures: products trimmed to the fields above; customer, member and cart IDs, ZIP code and
addresses replaced. The cart test left one Just Egg (16 oz) in the family's cart.
