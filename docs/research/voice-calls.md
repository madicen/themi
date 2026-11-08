# Automated vendor calls

As of 2026-11-08.

Today (prompt 27) Themi writes a call script and a person makes the call. This looks at
Themi placing the call itself: ringing a plumber, a pharmacy or a restaurant, asking its
questions, and reporting back. Use is a few calls a month, say 20 minutes in all.

## Providers

Prices are pay-as-you-go, US, per connected minute, from the pricing pages opened today.
"All-in" adds telephony, speech-to-text (STT), the model (LLM) and text-to-speech (TTS).

| Provider | What you pay per minute | All-in estimate | Own model or keys | Number | Setup |
|---|---|---|---|---|---|
| [Bland AI](https://www.bland.ai/pricing) | $0.14 talk time (Start plan, no monthly fee); covers STT, LLM, TTS | $0.14 plus telephony, which its FAQ says is billed separately (built-in Twilio at cost, or your own) | Own Twilio or SIP, yes; own LLM not stated | Inbound number included (Start) | Low: hosted agent, REST API |
| [Vapi](https://vapi.ai/pricing) | $0.05 hosting, plus providers at cost: STT $0.0095-0.0099, LLM $0.0077-0.0452, TTS $0.0146-0.0238; Twilio out $0.014 | About $0.10-0.15 (its own estimate: $82-129 per 1,000 min) | Yes: [own provider keys](https://docs.vapi.ai/customization/provider-keys) or a custom OpenAI-compatible LLM | 1 included | Medium: you assemble the stack |
| [Retell AI](https://www.retellai.com/pricing) | $0.055 voice engine; TTS from $0.015; LLM from about $0.003 (small models) to $0.16; telephony $0.015 | About $0.09-0.15 with a mid-sized model | Own telephony or SIP free; "Custom LLM" appears in its estimator, no price given | $2/month | Low to medium |
| [Twilio ConversationRelay](https://www.twilio.com/en-us/voice/pricing/us) | $0.07 (STT and TTS included, [per its docs](https://www.twilio.com/docs/voice/conversationrelay)) plus $0.014 outbound call | $0.084 plus our own model's tokens | Yes: text goes to our WebSocket and our model answers | $1.15/month | Medium: we write the WebSocket server |
| Twilio Media Streams, own speech model | $0.0044 stream plus $0.014 call | $0.018 plus the model; Retell resells GPT Realtime mini at $0.07/min all-in, a rough guide | Yes, entirely | $1.15/month | High: raw audio, turn-taking is ours |
| [ElevenLabs Agents](https://elevenlabs.io/pricing/api) | $0.08 plus LLM tokens; Free plan includes about 12-15 min a month | $0.08 plus LLM plus telephony | Own LLM not stated on the page | Telephony not on the pricing page (unconfirmed) | Low to medium |
| [OpenAI Live API over SIP](https://developers.openai.com/api/docs/guides/voice-sip.md) | Model tokens: [gpt-realtime](https://developers.openai.com/api/docs/pricing) audio $32 in / $64 out per 1M; mini $10 / $20 | Per-minute not published; needs our own SIP trunk (cost unconfirmed) | It is the model | From the SIP trunk | High: TLS/SRTP trunk, OpenAI only |
| [Synthflow](https://synthflow.ai/pricing) | Annual enterprise agreement only, "no rate by the minute" | n/a | n/a | n/a | Ruled out |

At 20 minutes a month every option costs under $4 in minutes. The number's monthly fee and
the work to build it matter more than the rate.

Call recording on Twilio is $0.0025/min, plus $0.0005/min a month to keep it.

## Quality and latency

No independent, audited figures exist. What's reported:

- [Techsy (May 2026)](https://techsy.io/en/blog/retell-ai-vs-vapi-vs-bland), tests from a Twilio
  number to a US mobile: median turn latency Vapi (tuned) about 540 ms, Retell about 610 ms,
  Bland about 820 ms; P95 1.5-2.1 s. It says a bigger model adds about 200 ms on any platform.
  It also says Retell doesn't take self-hosted models, which Retell's own page doesn't
  settle either way.
- Other comparison pages give different orders; most are written by a vendor or for
  affiliate links. Treat all of them as rough.
- Our own model through `themi.ai.router` from a Raspberry Pi adds a network hop and the
  router's retries. Expect the slow end of these ranges unless the model streams.

## Rules that apply

- **FCC, February 2024.** The FCC's declaratory ruling (FCC 24-17,
  [PDF](https://docs.fcc.gov/public/attachments/FCC-24-17A1.pdf), adopted 8 February 2024;
  the PDF couldn't be read here, so this follows
  [Orrick's summary](https://www.orrick.com/en/Insights/2024/02/Did-the-FCC-Really-Ban-AI-Generated-Voice-Calls-No-But-Restrictions-Apply))
  says AI-generated voices count as "artificial or prerecorded voice" under the TCPA. It is
  not a ban. Calls to mobiles need prior express consent (written consent for marketing).
  Such calls must state who is calling and give a call-back number.
- **What that means for Themi.** We'd be calling businesses about our own affairs, not
  marketing. Calls to a business landline look outside the TCPA's consent rules, but Orrick
  doesn't cover business lines, so that's unconfirmed. Many plumbers and small firms use a
  mobile, where consent is needed. The safe line: only call numbers the business publishes
  for customers, say at once that it's an automated assistant calling for the family, give
  the family's name and call-back number, and stop if asked.
- **Recording in California.** [Penal Code 632](https://california.public.law/codes/penal_code_section_632)
  needs "the consent of all parties to a confidential communication"; fines up to $2,500 per
  violation. Section 632.7 covers mobile calls without the "confidential" test (from search
  summaries, unconfirmed). So: no recording by default. A transcript for the family should
  be announced at the start ("this call is transcribed for the family").
- **Caller ID.** A Twilio number is a new, unknown number; branded calling is $0.12 a call
  on Twilio. Calls from an unknown number to a mobile may be labelled spam (unconfirmed).
- California's bot-disclosure law (SB 1001) covers bots online that sell or sway votes;
  whether it reaches a phone call is unconfirmed. We'd disclose anyway.

## Risks

- Businesses hang up on bots, or put them on hold forever. Pharmacies and restaurants often
  answer with a phone tree first.
- Disclosure costs some calls, but hiding it breaks trust and probably the rules.
- Wrong facts said on the family's behalf (a booking, a price agreed). Calls must be
  limited to asking and booking within limits the family set.
- Money and identity: no card numbers or prescriptions by voice; those stay with a person.
- Spend: a stuck call can run long. A hard limit per call (say 8 minutes) is needed.

## Recommendation

Twilio ConversationRelay with our own model through `themi.ai.router`:

- About $0.084 a minute plus tokens, $1.15 a month for the number. Under $5 a month at our
  volume.
- It keeps the repo's rules: model calls through the router (per-member keys, fallback),
  the call staged through the trust tiers, the result to the family through the outbox.
  The hosted platforms run their own model loop, which sits outside the router.
- Twilio is already the likely SMS provider (see `sms.md`), so one account.
- If quality isn't good enough, Retell or Vapi with our own keys are the fallback; both take
  Twilio numbers.

Keep the person-makes-the-call script (27) as the default. An automated call is Tier 1:
the family approves each one, with the script shown first.

## Proposed follow-up prompts

- V1: a call placed by Themi through Twilio ConversationRelay, model via the router, Tier 1
  per call, disclosure line, 8-minute cap, transcript summary to the asker.
- V2: a trial on five real calls (a restaurant, a pharmacy refill check, a plumber's quote),
  logged against the script, before V1 is offered by default.
