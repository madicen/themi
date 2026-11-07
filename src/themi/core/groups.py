"""Tool groups (CR8b): which tools go together, and the words that call for them.

A message gets the core tools and the groups its words (or the last few messages') call
for; `more_tools` brings in another mid-turn (P1, F33b). Each module registers the groups
its tools are in (`Module.tool_groups`), so a group without its modules isn't offered.
The settings group is the core's (`themi.core.tools.SETTINGS`).

Examples are for the embedding router (P7a): written fresh, never a routing case and never
the family's own words. The order is the order groups are offered in.
"""

from __future__ import annotations

from themi.core.tools import SETTINGS, ToolGroup

SCHEDULES = ToolGroup(
    name="schedules",
    description="repeating chores, plans, importance, check-in reviews",
    words=(
        "every|each|daily|weekly|monthly|repeat|schedule|plan|miles|km|minutes|weeks?"
        "|twice|once a|important|urgent|priority|check.?in|sunset|routine|always|remi"
        "nd|(?:mon|tues|wednes|thurs|fri|satur|sun)days|evenings|mornings|nights|week"
        "ends"
    ),
    examples=(
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
    tools=(
        "set_task_schedule",
        "set_task_plan",
        "set_task_importance",
        "set_check_in_reviews",
        "set_task_medicine",
    ),
    order=10,
)

CALENDAR = ToolGroup(
    name="calendar",
    description="calendar events, day summaries, drive times, blocking time",
    words=(
        "calendar|appointment|meeting|event|today|tomorrow|tonight|yesterday|(?:morni"
        "ng|afternoon|evening)(?!s?\\s+routines?)|day look|what'?s on|monday|tuesday|w"
        "ednesday|thursday|friday|saturday|sunday|weekend|drive|leave|traffic|block|t"
        "ime for|find (?:me )?time|summary"
    ),
    examples=(
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
    tools=(
        "add_calendar_event",
        "change_calendar_event",
        "delete_calendar_event",
        "merge_calendar_events",
        "day_summary",
        "drive_time",
        "block_time_for_task",
        "find_time_for_task",
    ),
    order=20,
)

WEB = ToolGroup(
    name="web",
    description="searching the web, reading a web page",
    words=(
        "look (?:it |that |this )?up|search|google|online|on the web|internet|website"
        "|find out|still (?:open|practi[cs]ing|in business|working)|phone number|open"
        "ing hours|reviews?"
    ),
    examples=(
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
    tools=(
        "search_web",
        "read_web_page",
    ),
    order=30,
)

RECIPES = ToolGroup(
    name="recipes",
    description="the family cookbook: finding and showing recipes",
    words=(
        "recipes?|cookbook|cook|bak(?:e|ing)|ingredients?|how (?:do|to) (?:i |we |you"
        " )?make|roast|instant pot|dressing|sauce|desserts?|soup|pancakes?|lasagna|ma"
        "sala|what (?:we|i) (?:would |will |'d |'ll )?need for|shop(?:ping)? for|doub"
        "le (?:it|the)|half (?:a )?batch|(?:makes|serves) (?:about )?\\d|walk (?:me|us"
        ") through|let'?s make|step by step|cooking|https?://\\S*(?:recipe|food|kitche"
        "n|cook|bak|eat|vegan)|what (?:can|could) (?:i|we) make|with what (?:we|i) ha"
        "ve"
    ),
    examples=(
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
    tools=(
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
    order=40,
)

LISTS = ToolGroup(
    name="lists",
    description="named lists, the wall's lists, usual stores",
    words=(
        "list|packing|ideas|tick|cross|check off|clear|things to cook|store|amazon|ta"
        "rget|costco|home depot"
    ),
    examples=(
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
    tools=(
        "create_list",
        "add_to_list",
        "tick_list_items",
        "remove_from_list",
        "show_lists",
        "delete_list",
        "put_list_on_wall",
        "set_usual_store",
    ),
    order=50,
)

WALL = ToolGroup(
    name="wall",
    description="the Cozyla wall: chore chart, routines, to-do lists",
    words="wall|cozyla|chart|chore|routine",
    examples=(
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
    tools=(
        "put_task_on_wall_list",
        "put_task_on_chore_chart",
        "set_chore_chart_limit",
        "change_chore_chart",
        "add_to_wall_routine",
        "show_routine",
        "show_routines",
        "set_routine",
        "remove_routine",
        "add_routine_item",
        "remove_routine_item",
        "tick_routine_item",
    ),
    order=60,
)

EMAIL = ToolGroup(
    name="email",
    description=("inboxes, expected emails, time-sensitive and important senders, the email audit"),
    words=(
        "e-?mail|inbox|gmail|sender|expect|bill|statement|confirmation|unsubscribe|au"
        "dit|time.sensitive|archive|noise|junk|spam|mark(?:ed)? (?:as )?read|forward"
    ),
    examples=(
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
        "Forward that email to Erin",
        "Send this email to jenn@example.com",
        "Can Michael see the email from the HOA?",
    ),
    tools=(
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
    order=70,
)

PANTRY = ToolGroup(
    name="pantry",
    description="the pantry and meal ideas",
    words=(
        "pantry|fridge|freezer|meal|dinner|lunch|breakfast|cook|recipe|out of|low on|"
        "running low|ran out|leftover|used (?:up|the last)|last of|finished the|picke"
        "d up|bought|got (?:some|more)|stocked|use (?:it |them )?up|using up|expir|go"
        "(?:es)? off|went off|safeway|\\bcart\\b|weekly shop"
    ),
    examples=(
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
    tools=(
        "update_pantry",
        "show_pantry",
        "suggest_meals",
        "fill_safeway_cart",
    ),
    order=80,
)

CALLS = ToolGroup(
    name="calls",
    description="phone calls to make for them",
    words="call|phone|ring|vendor|script",
    examples=(
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
    tools=(
        "draft_vendor_call",
        "log_call_outcome",
    ),
    order=90,
)

DEVICES = ToolGroup(
    name="devices",
    description=(
        "the washer, dryer, dishwasher, robot vacuum, pet feeders and litter box: run"
        "ning, done, time left, stuck, food left, last fed, sani-solution, errors"
    ),
    words=(
        "wash(?:er|ing)?\\b|dryer|drying|dishwasher|laundry|cycle|load\\b|appliance|how"
        " (?:much )?longer|time left|still running|is it done|robot|roborock|the vacu"
        "um\\b|vacuum'?s\\b|feeders?\\b|kibble|been fed|fed the (?:cat|dog)s?|pet food|c"
        "at food|dog food|litter|cat ?genie|sani.?solution|cartridge|granules?\\b"
    ),
    examples=(
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
    tools=("appliance_status",),
    order=100,
)

MAINTENANCE = ToolGroup(
    name="maintenance",
    description=(
        "seasonal and long-term upkeep: filters, gutters, fertilizing, their guides and notes"
    ),
    words=(
        "maintenance|upkeep|filters?\\b|gutters?|fertili[sz]|furnace|hvac|air con|smok"
        "e (?:alarm|detector)|water heater|water softener|descal|sprinklers?|winteri["
        "sz]|chimney|septic|dryer vent|caulk|seal(?:ant|ing)? the|oil change|tyres?\\b"
        "|tires?\\b|last time we|how do (?:i|we) (?:change|clean|service)"
    ),
    examples=(
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
    tools=(
        "set_maintenance",
        "remove_maintenance",
        "get_maintenance_guide",
        "log_maintenance",
    ),
    order=110,
)

SPENDING = ToolGroup(
    name="spending",
    description="money spent: takeout, eating out, business expenses",
    words=(
        "spent|spend|paid|\\$|expense|budget|takeout|take-out|doordash|door dash|uber "
        "eats|eating out|ate out|restaurant|receipt|cost"
    ),
    examples=(
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
    tools=(
        "log_spending",
        "spending_summary",
        "mark_business_expense",
        "remove_spending",
    ),
    order=120,
)

MUSIC = ToolGroup(
    name="music",
    description="their own music on Spotify: playing and pausing",
    words=(
        "spotify|playlist|\\bsong|\\balbum|\\bmusic\\b|play (?:some|my|the)\\b|pause (?:th"
        "e|my) (?:music|spotify|song)|put on (?:some|my)"
    ),
    examples=(
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
    tools=(
        "play_music",
        "pause_music",
    ),
    order=130,
)

BODY_DOUBLE = ToolGroup(
    name="body_double",
    description="body double sessions: quiet company, sprints, step by step",
    words=(
        "body.?doubl|sit with me|keep me company|company while|pomodoro|sprints?\\b|wo"
        "rk (?:alongside|with me)|stay with me while|focus session|while i (?:work|do"
        ")|quiet instead|step by step instead|always use (?:pomodoro|sprints|quiet)|\\"
        "blofi\\b|lo-fi|brown noise|play (?:some )?(?:rain|piano)"
    ),
    examples=(
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
    tools=(
        "start_body_double",
        "switch_body_double_mode",
        "end_body_double",
        "set_body_double_default",
        "set_job_category",
        "redo_step_picture",
        "send_step_picture",
        "choose_session_sound",
    ),
    order=140,
)

# Every group Themi knows, the core's settings group with them, in the order they're offered.
CATALOG: tuple[ToolGroup, ...] = tuple(
    sorted(
        (
            SCHEDULES, CALENDAR, WEB, RECIPES, LISTS, WALL, EMAIL, PANTRY, CALLS, DEVICES,
            MAINTENANCE, SPENDING, MUSIC, BODY_DOUBLE, SETTINGS,
        ),
        key=lambda g: g.order,
    )
)  # fmt: skip


def catalog_group_of(tool: str) -> str:
    """The group a tool is in among every known group, or "core": for reading old replies,
    whose groups were these."""
    return next((g.name for g in CATALOG if tool in g.tools), "core")
