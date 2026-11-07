"""Tools the model can call.

Each tool has a closed JSON Schema (`additionalProperties: false`, every
property required), so Claude can run it in strict mode and local models in
JSON mode get the same contract. Arguments are validated again before the
handler runs; a bad call comes back to the model as an error result, never
an exception in the agent loop.

Tools that change the world outside Themi (send an email, place an order)
are built with `@staged_tool`. Their handler can't act: it returns a
`Proposal`, and the registry stages that through the trust tiers, which run
it at once (Tier 2) or wait for the person's yes (Tier 1). The registry
refuses any side-effect tool built another way, so there's no path around
the tiers.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

import jsonschema

from themi.accounts.models import Member
from themi.ai.types import ToolCall, ToolResult, ToolSpec
from themi.core import naming

if TYPE_CHECKING:
    from themi.channels.events import Picture
    from themi.core.services import Services

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    member: Member
    services: Services
    request_text: str = ""  # what the person wrote this turn, for "did they ask for it?"
    previous_text: str = ""  # their message before it, for a follow-up like "and limes"
    said_before: str = ""  # Themi's last message to them, for an answer like "Yes please"
    # Each tool call this turn: "ok", "declined" (nothing to do) or "failed".
    outcomes: list[str] = field(default_factory=list)
    # A tool sent the answer itself, word for word (a day summary): the model's reply is
    # kept only as a short line (bug #89: it wrote the day out again).
    answered: list[str] = field(default_factory=list)
    # The tasks this turn's tools made or changed: what a reply says about who has them is
    # checked against them (bug #97).
    tasks: list[int] = field(default_factory=list)
    # The tool groups this turn sends (P1); `more_tools` adds to it.
    groups: set[str] = field(default_factory=set)
    # What complete_task said for each task marked done, warm word included: the reply
    # opens with them, word for word (bugs #111, #112: the model dropped the warm word, and
    # the phrasing rewrite dropped the rest).
    done: list[str] = field(default_factory=list)
    # What a tool said to them itself (a list add's confirmation, why it couldn't): when
    # every call this turn left one, they're the reply, and the model's words aren't sent
    # (bug #118: "Added to the list. Enjoy the sun." after an item about a sunny day).
    replies: list[str] = field(default_factory=list)
    # The replies above from something done just as they asked (Proposal.requested): when
    # every call this turn left one, the turn ends there, without another model round,
    # whose words wouldn't be sent (P2b).
    asked: list[str] = field(default_factory=list)
    # Open tasks create_task named as maybe the same job (bug #132): asked again this turn,
    # it's a different job, and it's made.
    named_twins: set[int] = field(default_factory=set)
    # Messages a tool sent them itself, with its own buttons (a held note's "Send now",
    # F29c; an approval card, F29d): that call's answer, so no model words follow it.
    cards: list[str] = field(default_factory=list)
    # Approval cards staged this turn (F29d): when every call only staged one, the cards
    # are the answer, and the model's words go only if they ask something of their own.
    staged: list[str] = field(default_factory=list)
    # Each call this turn: (tool, outcome, result text), for replies checked by tool (F30a).
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    # F34g: they sent a picture this turn, with `request_text` as its caption.
    picture: bool = False
    # F34l: the picture this turn can see: its own, or theirs from a moment ago. In memory
    # only; a tool that reads one (a recipe, F34m) uses this, never the model's retelling.
    image: Picture | None = None


@dataclass(frozen=True)
class Proposal:
    """What a side-effect tool wants done, for the trust tiers to decide on."""

    category: str
    summary: str
    executor: str
    payload: dict[str, Any] = field(default_factory=dict)
    # The person asked for exactly this in their own words (checked by the tool against
    # what they wrote, never the model's say-so). The trust tiers decide what that allows.
    requested: bool = False
    expires: datetime | None = None  # no use after then: an unanswered card lapses (#64)
    said: str | None = None  # the reply when it's done straight away (ToolContext.replies)


@dataclass(frozen=True)
class Done:
    """F33a: what a tool changed inside Themi, said as it is to them (and to the model).
    `asked`: what it changed was in their own words (`in_their_words`), so the line is the
    whole answer, and the turn can end without another model round (P2b, reply 237)."""

    said: str
    asked: bool = False


def in_their_words(ctx: ToolContext, title: str) -> bool:
    """Every word of the title (over two letters) is in what they wrote this turn: the
    tool did what they named, not what the model took them to mean."""
    from themi.core.lists import name_key  # lists builds its tools from this module

    said = name_key(ctx.request_text)
    words = [w for w in name_key(title).split() if len(w) > 2] or [name_key(title)]
    return all(w and w in said for w in words)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


class ToolFailed(Exception):
    """A tool couldn't do what was asked (no such task, not theirs...). The message goes
    back to the model as an error result, and the turn knows nothing was done. `reply`:
    what to tell them, when it's plain enough to say as it is (ToolContext.replies).
    `refused`: a naming check's kind of no (themi.core.naming), counted for P8a."""

    def __init__(self, message: str, reply: str | None = None, refused: str | None = None) -> None:
        super().__init__(message)
        self.reply = reply
        self.refused = refused


class ToolDeclined(Exception):
    """A tool has nothing to do (already done, already waiting...). The message goes
    back to the model as the tool's result; nothing was changed or staged."""


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: Handler
    proposes: bool = False  # True for @staged_tool: the handler returns a Proposal


def schema(properties: dict[str, Any]) -> dict[str, Any]:
    """A closed object schema where every property is required (strict-mode friendly)."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def tool(name: str, description: str, properties: dict[str, Any]) -> Callable[[Handler], Tool]:
    """A tool that only reads or records things inside Themi."""

    def wrap(handler: Handler) -> Tool:
        return Tool(ToolSpec(name, description, schema(properties)), handler)

    return wrap


def staged_tool(
    name: str, description: str, properties: dict[str, Any]
) -> Callable[[Handler], Tool]:
    """A tool with effects outside Themi. Its handler returns a Proposal."""

    def wrap(handler: Handler) -> Tool:
        spec = ToolSpec(name, description, schema(properties), side_effect=True)
        return Tool(spec, handler, proposes=True)

    return wrap


# ----- which tools a message gets (P1) ---------------------------------------------------
#
# Every message sent all the tools' schemas, about 8,000 tokens (bug #29). A core set always
# goes; the rest go by group when the message or the last few messages call for them, and
# `more_tools` adds a group mid-turn. A tool not in TOOL_GROUPS is core, so a new tool is
# never hidden by accident.

GROUPS: dict[str, tuple[str, str]] = {  # name: (what it's for, words that call for it)
    "schedules": (
        "repeating chores, plans, importance, check-in reviews",
        r"every|each|daily|weekly|monthly|repeat|schedule|plan|miles|km|minutes|weeks?|"
        r"twice|once a|important|urgent|priority|check.?in|sunset|routine|always|remind|"
        r"(?:mon|tues|wednes|thurs|fri|satur|sun)days|evenings|mornings|nights|weekends",
    ),
    "calendar": (
        "calendar events, day summaries, drive times, blocking time",
        r"calendar|appointment|meeting|event|today|tomorrow|tonight|yesterday|"
        r"(?:morning|afternoon|evening)(?!s?\s+routines?)|day look|what'?s on|monday|"
        r"tuesday|wednesday|thursday|friday|saturday|sunday|weekend|drive|leave|traffic|"
        r"block|time for|find (?:me )?time|summary",
    ),
    "web": (  # F30d: looking things up online
        "searching the web, reading a web page",
        r"look (?:it |that |this )?up|search|google|online|on the web|internet|website|"
        r"find out|still (?:open|practi[cs]ing|in business|working)|phone number|"
        r"opening hours|reviews?",
    ),
    "recipes": (  # RC1b: the family cookbook
        "the family cookbook: finding and showing recipes",
        r"recipes?|cookbook|cook|bak(?:e|ing)|ingredients?|how (?:do|to) (?:i |we |you )?make|"
        r"roast|instant pot|dressing|sauce|desserts?|soup|pancakes?|lasagna|masala|"
        r"what (?:we|i) (?:would |will |'d |'ll )?need for|shop(?:ping)? for|"
        r"double (?:it|the)|half (?:a )?batch|(?:makes|serves) (?:about )?\d|"
        r"walk (?:me|us) through|let'?s make|step by step|cooking|"
        r"https?://\S*(?:recipe|food|kitchen|cook|bak|eat|vegan)|"
        r"what (?:can|could) (?:i|we) make|with what (?:we|i) have",
    ),
    "lists": (
        "named lists, the wall's lists, usual stores",
        r"list|packing|ideas|tick|cross|check off|clear|things to cook|store|amazon|"
        r"target|costco|home depot",
    ),
    "wall": (
        "the Cozyla wall: chore chart, routines, to-do lists",
        r"wall|cozyla|chart|chore|routine",
    ),
    "email": (
        "inboxes, expected emails, time-sensitive and important senders, the email audit",
        r"e-?mail|inbox|gmail|sender|expect|bill|statement|confirmation|unsubscribe|audit|"
        r"time.sensitive|archive|noise|junk|spam|mark(?:ed)? (?:as )?read|forward",
    ),
    "pantry": (
        "the pantry and meal ideas",
        r"pantry|fridge|freezer|meal|dinner|lunch|breakfast|cook|recipe|out of|low on|"
        r"running low|ran out|leftover|used (?:up|the last)|last of|finished the|picked up|"
        r"bought|got (?:some|more)|stocked|use (?:it |them )?up|using up|expir|go(?:es)? off|"
        r"went off|safeway|\bcart\b|weekly shop",
    ),
    "calls": ("phone calls to make for them", r"call|phone|ring|vendor|script"),
    "devices": (
        "the washer, dryer, dishwasher, robot vacuum, pet feeders and litter box: running, "
        "done, time left, stuck, food left, last fed, sani-solution, errors",
        r"wash(?:er|ing)?\b|dryer|drying|dishwasher|laundry|cycle|load\b|appliance|"
        r"how (?:much )?longer|time left|still running|is it done|"
        r"robot|roborock|the vacuum\b|vacuum'?s\b|"
        r"feeders?\b|kibble|been fed|fed the (?:cat|dog)s?|pet food|cat food|dog food|"
        r"litter|cat ?genie|sani.?solution|cartridge|granules?\b",
    ),
    "maintenance": (
        "seasonal and long-term upkeep: filters, gutters, fertilizing, their guides and notes",
        r"maintenance|upkeep|filters?\b|gutters?|fertili[sz]|furnace|hvac|air con|"
        r"smoke (?:alarm|detector)|water heater|water softener|descal|sprinklers?|winteri[sz]|"
        r"chimney|septic|dryer vent|caulk|seal(?:ant|ing)? the|oil change|"
        r"tyres?\b|tires?\b|last time we|how do (?:i|we) (?:change|clean|service)",
    ),
    "spending": (
        "money spent: takeout, eating out, business expenses",
        r"spent|spend|paid|\$|expense|budget|takeout|take-out|doordash|door dash|uber eats|"
        r"eating out|ate out|restaurant|receipt|cost",
    ),
    "music": (  # BD5b: their own Spotify
        "their own music on Spotify: playing and pausing",
        r"spotify|playlist|\bsong|\balbum|\bmusic\b|play (?:some|my|the)\b|pause (?:the|my) "
        r"(?:music|spotify|song)|put on (?:some|my)",
    ),
    "body_double": (  # BD1a: company while they work
        "body double sessions: quiet company, sprints, step by step",
        r"body.?doubl|sit with me|keep me company|company while|pomodoro|sprints?\b|"
        r"work (?:alongside|with me)|stay with me while|focus session|while i (?:work|do)|"
        r"quiet instead|step by step instead|always use (?:pomodoro|sprints|quiet)|"
        r"\blofi\b|lo-fi|brown noise|play (?:some )?(?:rain|piano)",
    ),
    "settings": (
        "pausing messages, breaks, phrasing, quiet hours",
        r"pause|mute|quiet|stop (?:sending|messaging)|resume|phrasing|wording|tone|gentle|"
        r"plain|pushy|too many|limit|break\b|\brest\b|i'?m back|burnout|check-?ins?\b",
    ),
}
# P7a: plain examples of what calls for each group, for an embedding router (P7b) to
# compare messages with. They ship with Themi, so they're written fresh: never a routing case
# (tests/evals/routing_cases.json) and never the family's own words.
GROUP_EXAMPLES: dict[str, tuple[str, ...]] = {
    "schedules": (
        "Make this chore repeat every Monday",
        "The gutters need doing twice a year",
        "Change the dishes task to every other day",
        "Stop repeating the lawn task",
        "Mowing the lawn is a weekly thing",
        "That bill is important, there's a penalty if it's late",
        "This task matters more than the others",
        "Raise the importance of filing the taxes",
        "Increase my run by half a mile each week",
        "Start at ten push-ups and add two a week",
        "Check in with me about the garden every few days",
        "Make it repeat on the first of the month",
    ),
    "calendar": (
        "What's on my calendar today?",
        "Do I have anything Friday afternoon?",
        "Give me a rundown of my day",
        "What got done yesterday?",
        "Add a doctor's visit next Tuesday at ten",
        "Put the school concert on the family calendar",
        "Push the meeting back an hour",
        "Remove the dinner reservation from the calendar",
        "How long would it take to drive to the airport?",
        "When should I leave to get there by noon?",
        "Find me a free hour this week for the taxes",
        "Set aside Sunday afternoon for meal prep",
        "What's coming up next week?",
    ),
    "web": (  # F30d
        "Can you look up whether Dr. Scheinbach is still practicing?",
        "Search online for the vet's opening hours",
        "What's the phone number for Contemporary Dental in San Mateo?",
        "Find out if the farmers market is open on Sundays",
        "Google the reviews for that plumber",
        "Is the Thai place on El Camino still in business?",
        "Look up how long to cook farro",
        "Check the website for the library's holiday hours",
        "Search for kid-friendly hikes near Mountain View",
        "Can you find the recall notice for our car seat online?",
        "What does the internet say about rosemary for cats?",
        "Look it up: when does daylight saving end this year?",
    ),
    "recipes": (  # RC1b
        "Can you pull up the alfredo sauce recipe?",
        "Show me the ranch dressing from our cookbook",
        "What's in the chana masala?",
        "Find something with chickpeas in the cookbook",
        "Do we have a recipe for pancakes?",
        "What desserts are in our cookbook?",
        "How long do I roast carrots for?",
        "Send me the lasagna recipe",
        "How do I make the simple parmesan?",
        "What ingredients does the biryani need?",
        "I'd like to bake snickerdoodles, what's the recipe?",
        "Pull up a soup from the recipes",
    ),
    "lists": (
        "Make a list for the camping trip",
        "What lists do I have?",
        "Add a tent to the camping list",
        "Cross the batteries off the list",
        "Clear the finished items off my to-read list",
        "Remove the lantern from the camping list",
        "Get rid of the holiday list",
        "Show the camping list on the wall screen",
        "We usually buy printer ink from the office supply store",
        "Start a list of birthday gift ideas",
        "Tick off everything I already packed",
        "What's on my wish list?",
    ),
    "wall": (
        "Put flossing in my night routine",
        "What's in my morning routine?",
        "Add feeding the fish to the afternoon routine",
        "Show the dusting task on the chore chart",
        "Put the trash task on the wall's to-do list",
        "How many chores show on the chart at once?",
        "Show two chores at a time on the board",
        "Swap today's chore for another one",
        "I don't want that chore today, pick a different one",
        "Is laundry on the chore chart?",
        "Take the mirror cleaning off the board",
        "What's on the wall today?",
    ),
    "email": (
        "Is there anything in my inbox I should see?",
        "Archive the promotional emails",
        "Get rid of the newsletters in my inbox",
        "Mail from my accountant is always urgent",
        "Treat the store emails as low priority",
        "Don't archive that email from the landlord",
        "I'm waiting for a package tracking email",
        "Which emails are you watching for?",
        "Forget about the receipt email, it came",
        "Start watching my personal inbox too",
        "Let's sort out which senders matter",
        "Any unread emails that need a reply?",
        "Forward that email to Erin",  # F31d (idea #168)
        "Send this email to jenn@example.com",
        "Can Michael see the email from the HOA?",
    ),
    "pantry": (
        "We ran out of flour",
        "Running low on olive oil",
        "Picked up apples and bread today",
        "The chicken needs using by Wednesday",
        "What do we have in the fridge?",
        "Is there any pasta left?",
        "What should we cook tonight?",
        "Give me a dinner idea with what we have",
        "Something easy for lunch?",
        "Finished the cereal this morning",
        "The milk went off",
        "Got more coffee beans",
        "Load up the online grocery cart from the list",
    ),
    "calls": (
        "Write me a script for calling the landlord",
        "What do I say when I phone the pharmacy about a refill?",
        "Help me call the electric company about the bill",
        "I need to ring the garage about the car",
        "The phone company said they'd credit the account",
        "Called the school, they'll call back Monday",
        "Prepare me for a call with the bank",
        "Log that the vendor agreed to come Thursday",
        "Draft what to say to the moving company",
        "The plumber said next week",
        "I have to phone the clinic, can you help?",
        "Make me notes for calling customer service",
    ),
    "devices": (
        "How much longer on the wash?",
        "Is the dryer done yet?",
        "Is the dishwasher still running?",
        "How long is left on the laundry?",
        "Has the washer finished?",
        "Is anything running right now?",
        "When will the dryer be done?",
        "Is the dishwasher finished?",
        "What's the dryer at?",
        "Is the load of towels still going?",
        "How far along is the dishwasher?",
        "Is the robot vacuum still cleaning?",
        "Where's the vacuum stuck?",
        "Has the cat been fed this morning?",
        "How much food is left in the feeder?",
        "Is the litter box working?",
        "How much sani-solution is left?",
    ),
    "maintenance": (
        "The furnace filter wants changing every three months",
        "Add clearing the gutters to the maintenance list, spring and autumn",
        "We fertilize the fruit trees every six weeks from March to September",
        "Changed the fridge water filter today",
        "Cleaned the dryer vent, it was full of lint",
        "How do I flush the water heater again?",
        "What did we use on the lawn last time?",
        "When's the smoke alarm test next due?",
        "Take the pool cover off the upkeep list",
        "The sprinkler blowout is done in October only",
        "What maintenance is coming up?",
        "Add a step to the AC service: check the drain line",
    ),
    "spending": (
        "We spent $30 on burgers",
        "Got takeout tonight, $45",
        "How much have we spent eating out?",
        "What's our takeout total this month?",
        "That dinner was a work expense",
        "Mark the coffee as business",
        "Delete the pizza from spending",
        "That charge was logged twice",
        "Paid $18 for delivery",
        "Are we over our eating out budget?",
        "Lunch out with a client, $60",
        "Show me what we spent this week",
    ),
    "music": (  # BD5b
        "Play my focus playlist on Spotify",
        "Put on some jazz",
        "Pause the music",
        "Play the Abbey Road album",
        "Can you play my running playlist?",
        "Stop the song",
        "Put on something calm on Spotify",
        "Play some instrumental music",
        "Start my morning playlist",
        "Pause Spotify for a minute",
        "Play that new Taylor Swift album",
        "Music please, something upbeat",
    ),
    "body_double": (  # BD1a
        "Can you sit with me while I sort the paperwork?",
        "Body double me through the dishes",
        "Pomodoro the garage clean-out",
        "Keep me company while I write the report",
        "I need some company while I study",
        "Let's do sprints on the inbox",
        "Stay with me while I fold the clothes",
        "Work alongside me for an hour on the essay",
        "Quiet company for 45 minutes please",
        "Switch to sprints",
        "Quiet instead",
        "Start a focus session on the budget",
    ),
    "settings": (
        "I'm going to rest for twenty minutes",
        "Taking five",
        "I'm done with my break",
        "Back now",
        "Pause the laundry reminders for the weekend",
        "No nudges for the rest of the day",
        "Stop messaging me for a few hours",
        "Hold off on the check-ins until Monday",
        "You can start the meal reminders again",
        "Use plainer wording with me",
        "Can you phrase things more softly?",
        "Too many messages today",
    ),
}
TOOL_GROUPS: dict[str, str] = {
    **dict.fromkeys(
        (
            "find_recipe",
            "show_recipe",
            "add_recipe_to_grocery_list",
            "set_recipe_yield",
            "start_cooking",
            "stop_cooking",
            "recipe_from_link",
            "recipe_from_picture",
            "find_web_recipe",
            "save_recipe_to_cookbook",
            "cookbook_recipes_we_can_make",
        ),
        "recipes",
    ),  # RC1b, RC2a, RC2b, RC3a
    **dict.fromkeys(("search_web", "read_web_page"), "web"),
    **dict.fromkeys(("play_music", "pause_music"), "music"),  # BD5b
    **dict.fromkeys(
        (
            "start_body_double",
            "switch_body_double_mode",
            "end_body_double",
            "set_body_double_default",
            "set_job_category",
            "redo_step_picture",  # BD4b
            "send_step_picture",
            "choose_session_sound",  # BD5a
        ),
        "body_double",
    ),
    **dict.fromkeys(("start_break", "end_break", "set_burnout_check_in"), "settings"),
    **dict.fromkeys(
        ("log_spending", "spending_summary", "mark_business_expense", "remove_spending"),
        "spending",
    ),
    **dict.fromkeys(
        (
            "set_task_schedule",
            "set_task_plan",
            "set_task_importance",
            "set_check_in_reviews",
            "set_task_medicine",
        ),
        "schedules",
    ),
    **dict.fromkeys(
        (
            "add_calendar_event",
            "change_calendar_event",
            "delete_calendar_event",
            "merge_calendar_events",
            "day_summary",
            "drive_time",
            "block_time_for_task",
            "find_time_for_task",
        ),
        "calendar",
    ),
    **dict.fromkeys(
        (
            "create_list",
            "add_to_list",
            "tick_list_items",
            "remove_from_list",
            "show_lists",
            "delete_list",
            "put_list_on_wall",
            "set_usual_store",
        ),
        "lists",
    ),
    **dict.fromkeys(
        (
            "put_task_on_wall_list",
            "put_task_on_chore_chart",
            "set_chore_chart_limit",
            "change_chore_chart",
            "add_to_wall_routine",
            "show_routine",
            # R1a: Themi's own routines, called for by the same words
            "show_routines",
            "set_routine",
            "remove_routine",
            "add_routine_item",
            "remove_routine_item",
            "tick_routine_item",
        ),
        "wall",
    ),
    **dict.fromkeys(
        (
            "expect_email",
            "list_expected_emails",
            "forget_expected_email",
            "set_urgent_senders",
            "set_inbox_watched",
            "inbox_setup",
            "keep_email",
            "start_email_audit",
            "set_sender_levels",
            "archive_noise_emails",
            "forward_email",
        ),
        "email",
    ),
    **dict.fromkeys(
        ("update_pantry", "show_pantry", "suggest_meals", "fill_safeway_cart"), "pantry"
    ),
    **dict.fromkeys(("draft_vendor_call", "log_call_outcome"), "calls"),
    "appliance_status": "devices",
    **dict.fromkeys(
        ("set_maintenance", "remove_maintenance", "get_maintenance_guide", "log_maintenance"),
        "maintenance",
    ),
    **dict.fromkeys(("pause_messages", "resume_messages", "set_phrasing"), "settings"),
}


# ----- near-twin tools (P6) --------------------------------------------------------------
#
# Some tools sound alike and do very different things, and the model used whichever twin it
# had (the 2026-10-29 evals: add_to_grocery_list for "used the last of the olive oil",
# because update_pantry's group wasn't sent). A twin set travels whole, whatever the router
# chose, and its paragraph goes in the system prompt with it, so the tools' own
# descriptions say what each does and the paragraph says which is which.


@dataclass(frozen=True)
class Twins:
    name: str
    tools: tuple[str, ...]
    text: str  # how to tell them apart, for the system prompt


TWINS: tuple[Twins, ...] = (
    Twins(
        "food and buying",
        ("update_pantry", "add_to_grocery_list", "add_to_things_to_buy", "add_to_list"),
        """\
Food and buying are four different places:
- update_pantry records what the house has: "used the last of the olive oil" is out,
  "running low on rice" is low, "just picked up eggs" is plenty. It offers low or out
  staples for the grocery list itself, so don't add them to the list as well.
- add_to_grocery_list is food someone asks to have on the grocery list ("put cumin on the
  grocery list", "bananas for this week's shop").
- add_to_things_to_buy is anything to buy that isn't food ("we need light bulbs", "add AA
  batteries").
- add_to_list is one of Themi's named lists, by its name ("add sunscreen to the packing
  list").
When it could go on more than one list, ask_which_list asks with buttons; don't guess,
and don't ask in words.""",
    ),
    Twins(
        "quiet time",
        ("start_break", "pause_messages"),
        """\
Quiet time is two different things:
- start_break is the person resting ("I'm taking a break", "going to lie down for 30
  minutes"): task nudges and check-ins wait, then one message asks whether to end or
  extend it. "I'm back" is end_break.
- pause_messages holds Themi's own messages for a while ("hold the meal reminders today",
  "don't send me anything for a couple of hours"): it's about Themi's messages, not their
  resting.
Neither is a busy time.""",
    ),
    Twins(
        "rules or tasks",
        ("propose_rule", "create_task", "set_task_schedule"),
        """\
Rules and tasks are different things:
- propose_rule is how Themi itself behaves ("from now on, give me steps as bullet
  points", "always archive store promos"), as a draft they lock in themselves. When they
  call it a rule ("new rule: ...", "make it a rule that ..."), it's propose_rule.
- create_task is something a person does, once or repeating ("return the library books";
  "ask my husband to fix the squeaky door" is a task assigned to him). Chores, schedules
  and the steps of a job are tasks, never rules, even when someone describes how a chore
  should go from now on.
- set_task_schedule is when a task repeats: after create_task for a new one ("I water the
  plants every Sunday" is both, and so is "always remind me about the bins on Tuesdays").""",
    ),
)


def twins_text(names: Iterable[str]) -> str:
    """The paragraphs for the twin sets these tools belong to, for the system prompt."""
    sent = set(names)
    return "\n\n".join(t.text for t in TWINS if sent & set(t.tools))


_GROUP_WORDS = {
    name: re.compile(rf"\b(?:{words})", re.IGNORECASE) for name, (_, words) in GROUPS.items()
}


# F34l: a picture turn gets the groups a picture usually starts (a list's items, an event, a
# recipe), whatever its words; guides and bug reports are core already. Not every group:
# that would double the prompt (about 28k characters to 56k), and `more_tools` is there.
PICTURE_GROUPS = frozenset({"lists", "calendar", "recipes"})
PICTURE_LOG = "[a picture]"  # how the message log keeps one (themi.channels.telegram)
YES_TO_IT = re.compile(
    r"^(?:yes|yep|yeah|yup|ok|okay|sure|please|go ahead|do it|sounds good|"
    r"add (?:them|it|those|these|all|them all|all of them)|save (?:it|that|this)|"
    r"put it (?:on|in)(?: (?:the|my|our))? (?:calendar|list))"
    r"(?: (?:please|thanks|thank you|add (?:them|it|those|these)|do it|go ahead))*$"
)


def plain_words(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s&'/-]", " ", text).split()).lower()


def answers_picture_question(ctx: ToolContext, words: Sequence[str]) -> bool:
    """F34gb, F34l: they sent a picture, Themi asked about it ("Add milk and eggs to the
    grocery list?"), and they said yes. The question was Themi's, it named every one of
    `words` (list items, an event's title and day, a recipe's name), and the yes is
    theirs. The caller checks the question asked for its kind of thing."""
    if not words or not ctx.previous_text.startswith(PICTURE_LOG) or "?" not in ctx.said_before:
        return False
    answer = ctx.request_text.strip().lower().rstrip("!. ")
    if answer not in ("👍", "✅") and not YES_TO_IT.match(plain_words(ctx.request_text)):
        return False
    asked = plain_words(ctx.said_before)
    return all(re.search(rf"\b{re.escape(plain_words(w))}\b", asked) for w in words)


def choose_groups(texts: Sequence[str]) -> set[str]:
    """The groups these messages call for (this one and the last few)."""
    joined = " ".join(texts)
    return {name for name, pattern in _GROUP_WORDS.items() if pattern.search(joined)}


# Old tool names still answered for one release (a model or a saved turn may use them):
# the call goes to the new tool, its new fields empty (F29a).
ALIASES = {"move_calendar_event": "change_calendar_event"}


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, t: Tool) -> None:
        if t.spec.name in self._tools:
            raise ValueError(f"tool {t.spec.name} is already registered")
        if t.spec.side_effect != t.proposes:
            raise ValueError(
                f"tool {t.spec.name}: side-effect tools must be built with @staged_tool "
                "so they go through the trust tiers"
            )
        self._tools[t.spec.name] = t

    def specs(self, groups: set[str] | None = None) -> list[ToolSpec]:
        """Every tool, or (P1) the core and these groups', with any twin set (P6) they
        touch. Sorted, so the tool list (part of the cached prompt prefix) is stable."""
        chosen = {
            name
            for name in self._tools
            if groups is None or TOOL_GROUPS.get(name, "core") in groups | {"core"}
        }
        for twins in TWINS:  # P6: a twin set goes whole
            if chosen & set(twins.tools):
                chosen |= set(twins.tools) & self._tools.keys()
        specs = [self._tools[name].spec for name in sorted(chosen)]
        if groups is None:
            return specs
        offer = more_tools_for(groups)  # F33b: only what this turn doesn't have
        rest = [spec for spec in specs if spec.name != more_tools.spec.name]
        if offer is None or len(rest) == len(specs):
            return rest
        return sorted([*rest, offer], key=lambda spec: spec.name)

    def specs_for(self, groups: set[str], routing: str = "groups") -> list[ToolSpec]:
        """The tools one model call gets. P5's "all" is every tool but more_tools, which
        would have nothing to add."""
        if routing == "all":
            return [spec for spec in self.specs() if spec.name != more_tools.spec.name]
        return self.specs(groups)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        t = self._tools.get(call.name)
        if t is None and call.name in ALIASES and (t := self._tools.get(ALIASES[call.name])):
            empty = dict.fromkeys(t.spec.input_schema["properties"], "")
            call = replace(call, arguments={**empty, **call.arguments})
        if t is None:
            return ToolResult(call.id, f"There's no tool called {call.name}.", is_error=True)
        result, outcome = await self._run(t, call, ctx)
        ctx.outcomes.append(outcome)
        ctx.calls.append((call.name, outcome, result.content))
        task_id = call.arguments.get("task_id")
        if outcome == "ok" and isinstance(task_id, int) and task_id > 0:  # 0 is none (F23e)
            ctx.tasks.append(task_id)
        named = naming.task_of(call.arguments)
        if outcome == "ok" and call.name in naming.CHECKED and named is not None:  # P8a
            naming.NamingRefusals(ctx.services.store.db).went_through(
                ctx.member.id, call.name, named
            )
        return result

    async def _run(self, t: Tool, call: ToolCall, ctx: ToolContext) -> tuple[ToolResult, str]:
        call = replace(call, arguments=_as_typed(call.arguments, t.spec.input_schema))
        defaults = {  # F29g: a field added later, with its default, when a call leaves it out
            k: p["default"] for k, p in t.spec.input_schema["properties"].items() if "default" in p
        }
        if defaults.keys() - call.arguments.keys():
            call = replace(call, arguments={**defaults, **call.arguments})
        try:
            jsonschema.validate(call.arguments, t.spec.input_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult(call.id, f"Invalid arguments: {exc.message}", is_error=True), "failed"
        try:
            output = await t.handler(ctx, call.arguments)
            if t.proposes:
                output = await self._stage(output, ctx)
            elif isinstance(output, Done):
                if output.asked:  # otherwise the model says it, as before F33a
                    ctx.replies.append(output.said)
                    ctx.asked.append(output.said)
                output = output.said
            elif not isinstance(output, str):
                raise TypeError(f"tool {call.name} returned {type(output).__name__}, not text")
        except ToolDeclined as exc:
            return ToolResult(call.id, str(exc)), "declined"
        except ToolFailed as exc:
            if exc.reply:
                ctx.replies.append(exc.reply)
            if exc.refused:
                naming.NamingRefusals(ctx.services.store.db).refused(
                    ctx.member.id, call.name, exc.refused, naming.task_of(call.arguments)
                )
            return ToolResult(call.id, f"{exc} Nothing was changed.", is_error=True), "failed"
        except Exception as exc:
            log.exception("Tool %s failed for member %s", call.name, ctx.member.id)
            failure = f"The tool failed ({type(exc).__name__}). Nothing was changed."
            return ToolResult(call.id, failure, is_error=True), "failed"
        log.info("Tool %s ran for member %s", call.name, ctx.member.id)
        return ToolResult(call.id, output), "ok"

    @staticmethod
    async def _stage(proposal: Any, ctx: ToolContext) -> str:
        if not isinstance(proposal, Proposal):
            raise TypeError("a staged tool must return a Proposal")
        outcome = await ctx.services.autonomy.stage(
            proposal.category,
            ctx.member,
            proposal.summary,
            proposal.payload,
            proposal.executor,
            interactive=True,  # tools run inside a conversation
            requested=proposal.requested,
            expires=proposal.expires,
        )
        action = outcome.action
        if action.status == "pending":
            ctx.staged.append(proposal.summary)
            return (
                f"Staged for approval (action {action.id}): {proposal.summary}. Nothing happens "
                "until they say yes; don't describe it as done."
            )
        if action.status == "done":
            if proposal.said:
                ctx.replies.append(proposal.said)
                if proposal.requested:
                    ctx.asked.append(proposal.said)
            return f"Done automatically (action {action.id}): {outcome.message}"
        return f"Tried but it failed (action {action.id}); it can be retried: {outcome.message}"


_INTEGER = re.compile(r"[+-]?\d+")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")


def _as_typed(value: Any, schema: dict[str, Any]) -> Any:
    """Numbers and true/false that came as text, as the schema's type (eval energy-plumber:
    Gemini sent log_energy_note's effect as "-3"; its function schemas take only text
    choices). Anything else is left for the schema check to refuse."""
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _as_typed(v, props[k]) if k in props else v for k, v in value.items()}
    if kind == "array" and isinstance(value, list) and "items" in schema:
        return [_as_typed(v, schema["items"]) for v in value]
    if not isinstance(value, str):
        return value
    text = value.strip()
    if kind == "integer" and _INTEGER.fullmatch(text):
        return int(text)
    if kind == "number" and _NUMBER.fullmatch(text):
        return float(text)
    if kind == "boolean" and text.lower() in ("true", "false"):
        return text.lower() == "true"
    return value


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _more_tools_text(groups: Sequence[str]) -> str:
    return (
        "Bring in more of Themi's tools for this conversation, when what they ask needs ones "
        "you don't have yet. groups: "
        + "; ".join(f"'{name}' ({GROUPS[name][0]})" for name in groups)
        + "."
    )


def _more_tools_args(groups: Sequence[str]) -> dict[str, Any]:
    return {"groups": {"type": "array", "items": {"type": "string", "enum": list(groups)}}}


@tool("more_tools", _more_tools_text(list(GROUPS)), _more_tools_args(list(GROUPS)))
async def more_tools(ctx: ToolContext, args: dict[str, Any]) -> str:
    added = [g for g in args["groups"] if g in GROUPS and g not in ctx.groups]
    ctx.groups.update(added)
    if added:
        return f"Added the {', '.join(added)} tools; use them now."
    # F33b: only groups not sent are offered, so this is an old list or a muddle; say
    # what's here instead of a bare "here already" (reply 237 wandered for three rounds).
    here = [g for g in dict.fromkeys(args["groups"]) if g in GROUPS]
    names = sorted(n for n, g in TOOL_GROUPS.items() if g in here and ctx.services.tools.get(n))
    if not names:
        return "Those tools are here already."
    return (
        f"The {' and '.join(here)} tools are here already: {', '.join(names)}. Use one of them now."
    )


def more_tools_for(groups: set[str]) -> ToolSpec | None:
    """F33b: more_tools as one turn gets it, offering only the groups it doesn't have yet
    (29 of 41 calls in a week asked for ones already sent). None when every group is in."""
    missing = [g for g in GROUPS if g not in groups]
    if not missing:
        return None
    return ToolSpec(
        more_tools.spec.name, _more_tools_text(missing), schema(_more_tools_args(missing))
    )
