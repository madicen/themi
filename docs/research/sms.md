# SMS as an extra channel

As of 2026-11-08.

Telegram is Themi's channel. SMS would be an extra one: a fallback when Telegram is down or
a phone has no data, or for urgent nudges. Volume: 100-300 texts a month to two people.

## Twilio US SMS prices

From [Twilio's US SMS pricing](https://www.twilio.com/en-us/sms/pricing/us), pay-as-you-go:

| Item | Price |
|---|---|
| SMS out, per segment (local 10DLC or toll-free) | $0.0083 |
| SMS in, per segment | $0.0083 |
| MMS out / in (local) | $0.022 / $0.0165 |
| Local number | $1.15 a month |
| Toll-free number | $2.15 a month |
| Failed message | $0.001 each |

Carrier fees go on top, per segment, long code and toll-free:

| Carrier | SMS out | SMS in |
|---|---|---|
| AT&T | $0.0035 | $0.0035 |
| T-Mobile | $0.0045 | $0.0025 |
| Verizon | $0.005 | not clear on the page (0.007 appears in the row) |
| US Cellular | $0.005 (toll-free $0.0045) | $0.0025 |

A segment is 160 GSM characters, or 70 if the text has an emoji or other non-GSM character
(general knowledge, unconfirmed here). Themi's nudges often run past 160 characters, so
budget two segments a message.

## A2P 10DLC

US carriers require app-sent texts from ordinary 10-digit numbers to be registered with The
Campaign Registry. [Twilio's 10DLC page](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
says unregistered traffic carries extra carrier fees; that Twilio blocks it outright is from
memory (unconfirmed).

Steps on Twilio:

1. A paid account and a customer profile (Trust Hub).
2. Brand registration. Without a tax ID (EIN), a household registers as a **Sole
   Proprietor**: [Twilio's guide](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview)
   says it's for US or Canadian customers "who do not have a business Tax ID". Twilio texts
   a code to a US mobile, to be answered within 24 hours. Approval "typically occurs within
   a few minutes". With an EIN, **Low-Volume Standard** or **Standard** instead.
3. Campaign registration: use case, at least two sample messages, a privacy policy URL, a
   terms URL and how people opt in. The Themi website could host the two pages.
4. Campaign vetting by the carriers' vetting partner: "up to 5 business days for standard
   use cases"; ask support after 10 days. A secondary source says 10-15 days lately
   (unconfirmed).
5. Attach the number to the campaign's Messaging Service.

Fees, one-time and monthly:

| Fee | Sole Proprietor | Low-Volume Standard | Standard |
|---|---|---|---|
| Brand registration (one-time) | $4 on [Twilio's 10DLC page](https://www.twilio.com/en-us/phone-numbers/a2p-10dlc); $4.50 per [Sociocs, July 2026](https://www.sociocs.com/post/twilio-10dlc-explained/) | $4 (Twilio) | $44 (Twilio) |
| Campaign vetting (one-time) | $15 | $15 | $15 |
| Campaign (monthly) | $2 | $1.50-10 | $1.50-10 |

Twilio's own pages disagree with the newer secondary sources on the brand fee; expect $4 to
$4.50. Twilio's help centre article with the fee table wouldn't load.

Sole Proprietor limits: one campaign per brand, one 10DLC number per campaign, 1,000
segments a day to T-Mobile and about 3,000 a day across carriers (Twilio's 10DLC doc). The
same mobile can back at most three Sole Proprietor brands. Throughput is 1 message a second
per Sociocs (not stated on Twilio's pages). All far above our need.

## Toll-free verification instead

- A toll-free number ($2.15 a month) must be verified before it can send. Twilio
  ["reviews TFV requests within three business days"](https://www.twilio.com/docs/messaging/compliance/toll-free/api-onboarding).
- Needs: business name, website, use case, a sample message, proof of opt-in (an image
  URL), estimated monthly volume, and an approved customer profile.
- Since 17 February 2026 a business registration number is required "for all business types
  expect sole proprietorships" ([changelog](https://www.twilio.com/en-us/changelog/business-registration-numbers-required-for-toll-free-messaging-p)),
  so a household can verify as `SOLE_PROPRIETOR`.
- No verification fee on any page opened; no campaign fee. Not confirmed that there is none.
- Same per-segment rate and carrier fees as 10DLC on Twilio.

## Cheaper providers

| Provider | SMS out / in (local) | Toll-free out / in | Number a month | Carrier fees |
|---|---|---|---|---|
| [Telnyx](https://telnyx.com/pricing/messaging) | $0.004 / $0.004 | $0.0055 / $0.0055 | $1.00 | Passed through, similar to Twilio's |
| [Plivo](https://www.plivo.com/sms/pricing/us/) | $0.0077 / $0.0077 | $0.0079 / $0.0079 | $0.50 local, $1.00 toll-free | Passed through, same as Twilio's |

Neither page lists 10DLC fees; they go through the same registry, so expect similar ones
(unconfirmed). At our volume the saving is about $1-3 a month.

## What it costs us

300 messages out, two segments each, carrier fee about $0.0045: 600 x ($0.0083 + $0.0045) =
about $7.70. Replies in, say 100 single segments: about $1.20.

| Route | One-time | Monthly (300 texts) |
|---|---|---|
| Twilio 10DLC, Sole Proprietor | about $19-19.50 | about $9 + $1.15 + $2 = about $12 |
| Twilio toll-free, verified | $0 found | about $9 + $2.15 = about $11 |
| At 100 texts | as above | about $5-6 |

## Recommendation

- SMS is worth it only as a fallback for urgent messages (a "now" nudge Telegram didn't
  deliver), not as a second full channel. Most months that's far under 100 texts.
- Use Twilio, the likely voice-call provider too, so one account. A verified toll-free
  number, as a sole proprietor: no campaign fees, three-day review, about $2.15 a month plus
  a few dollars of messages. If toll-free verification is refused, register a 10DLC Sole
  Proprietor brand ($4-4.50 plus $15 once, $2 a month).
- Both need a privacy policy and terms page and a record that Michael and Erin opted in;
  STOP must work.
- Telnyx halves the per-message rate, but not worth a second vendor at this volume.

## Proposed follow-up prompts

- S1: SMS fallback through the outbox for urgent messages Telegram didn't deliver, Twilio
  toll-free, STOP/START handled, segments counted and capped per month.
- S0 (Michael, not code): open the Twilio account, buy the number, submit toll-free
  verification with the opt-in and privacy pages.
