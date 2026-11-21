# Shipping email fixtures (PT3)

Written for Themi's tests, not copied from anyone's inbox: each follows the shape of the
public examples of that kind of email (the senders' help pages and screenshots), with
made-up names, addresses and order numbers. The tracking numbers are the published test
numbers in `tracking_number_data` (`src/themi_google/tracking_data/`), so their check
digits hold. What each is:

| File | Sender | Shape |
| --- | --- | --- |
| `informed_delivery.html` | USPS Informed Delivery daily digest | "Your Daily Digest", mail pieces, then "Arriving Today/Expected" packages, each with its tracking number as a link |
| `ups_my_choice.html` | UPS My Choice | "Your UPS Package is out for delivery", the delivery window, the shipper, a Track link |
| `fedex_delivery_manager.html` | FedEx Delivery Manager | "FedEx Shipment ... Delivery Exception", the number in the subject and a Track link |
| `amazon_shipped.html` | Amazon | "Shipped: ...", "Arriving Friday", a Track package button (no number in the text) |
| `shopify_shipped.html` | A Shopify shop | "Your order is on the way", carrier and number as text, a Track link through a click redirect |
| `chewy_shipped.txt` | Chewy (plain text) | "Your order has shipped", the carrier, the number on its own line under "Tracking #" |
