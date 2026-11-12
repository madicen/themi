"""CR10b1: the home pack's tool groups (see themi.core.groups)."""

from __future__ import annotations

from themi.core.tools import ToolGroup

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


PANTRY = ToolGroup(
    name="pantry",
    description="the pantry and meal ideas",
    words=(
        "pantry|fridge|freezer|meal|dinner|lunch|breakfast|\\bate\\b|eaten|snack|cook|recipe|"
        "out of|low on|"
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
        "Just had lunch",
    ),
    tools=(
        "update_pantry",
        "show_pantry",
        "suggest_meals",
        "log_meal",
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
        "ning, done, time left, stuck, food left, last fed, sani-solution, errors; feed"
        "ing a pet from its feeder now"
    ),
    words=(
        "wash(?:er|ing)?\\b|dryer|drying|dishwasher|laundry|cycle|load\\b|appliance|how"
        " (?:much )?longer|time left|still running|is it done|robot|roborock|the vacu"
        "um\\b|vacuum'?s\\b|feeders?\\b|\\bfeed\\b|dispens|kibble|been fed|fed the (?:"
        "cat|dog)s?|pet food|c"
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
        "Feed the cat",
        "Give Mochi a portion from the feeder",
        "Is the litter box working?",
        "How much sani-solution is left?",
    ),
    tools=("appliance_status", "feed_pet"),
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
    description="money spent: takeout, eating out, business expenses, expense sheets",
    words=(
        "spent|spend|paid|\\$|expense|budget|takeout|take-out|doordash|door dash|uber "
        "eats|eating out|ate out|restaurant|receipt|cost|spreadsheet|sheet|mileage|miles|"
        "reimburs|track what"
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
        "Start a sheet for business travel",
        "Add a mileage tab to the business spreadsheet",
        "About $40 on paint for the kitchen project, pretty sure",
        "The Merit one is right",
    ),
    tools=(
        "log_spending",
        "spending_summary",
        "mark_business_expense",
        "remove_spending",
        "make_expense_sheet",
        "change_expense_sheet",
        "add_expense",
        "verify_expense",
        "move_expense",
        "expense_summary",
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
