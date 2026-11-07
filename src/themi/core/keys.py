"""Keys for what features provide, for looking one up without importing it (CR3).

    services.maybe(keys.triage)  # EmailTriage | None

Each key names a class; the object is filed under that class's name. The names match
what the services hub held before CR3 (`services.triage`), so old code reads the same.
A key here is feature code, never core: CR10 splits this file by pack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from themi.modules.registry import Key

if TYPE_CHECKING:
    from themi.connectors.catgenie import CatGenieWatcher
    from themi.connectors.gcal import CalendarSync
    from themi.connectors.gcal.busy import CalendarBusy
    from themi.connectors.gmail import GmailSync
    from themi.connectors.google import GoogleAccounts
    from themi.connectors.homeconnect import HomeConnectAccount
    from themi.connectors.roborock import RoborockWatcher
    from themi.connectors.thinq import ThinqWatcher
    from themi.connectors.tuya import TuyaWatcher
    from themi.core.appliances import Appliances
    from themi.core.body_double import BodyDouble
    from themi.core.breaks import Breaks
    from themi.core.burnout import Burnout
    from themi.core.business_hours import BusinessHours
    from themi.core.buying import ThingsToBuy
    from themi.core.calendar_copies import CalendarCopies
    from themi.core.calls import VendorCalls
    from themi.core.chore_chart import ChartQueue
    from themi.core.conversation_mode import ConversationMode
    from themi.core.cookbook_save import CookbookSave
    from themi.core.cooking import Cooking
    from themi.core.cozyla_routines import CozylaRoutines
    from themi.core.cozyla_todos import CozylaTodos
    from themi.core.day_summary import DaySummary
    from themi.core.dishwasher import Dishwasher
    from themi.core.email_audit import EmailAudit
    from themi.core.events import Events
    from themi.core.expected import ExpectedEmails
    from themi.core.feedback import FeedbackChat
    from themi.core.feeders import Feeders
    from themi.core.focus import Focus
    from themi.core.follow_ups import FollowUps
    from themi.core.google_tasks import GoogleTasksInbox
    from themi.core.groceries import GroceryList
    from themi.core.guides import Guides
    from themi.core.habits import HabitReserve
    from themi.core.journal import Journal
    from themi.core.laundry import Laundry
    from themi.core.liaison import Liaison
    from themi.core.lists import Lists
    from themi.core.litter_box import LitterBox
    from themi.core.maintenance import Maintenance
    from themi.core.meals import Meals
    from themi.core.memory import Memory
    from themi.core.music import Music
    from themi.core.noise_digest import NoiseDigest
    from themi.core.pantry import Pantry
    from themi.core.reactions import Reactions
    from themi.core.recipe_groceries import RecipeGroceries
    from themi.core.recipe_ideas import RecipeIdeas
    from themi.core.recipes import Recipes
    from themi.core.routines import Routines
    from themi.core.safeway import SafewayCart
    from themi.core.senders import SenderSuggestions
    from themi.core.spending import Spending
    from themi.core.taking import Taking
    from themi.core.task_blocks import TaskBlocks
    from themi.core.tasks import TaskBoard
    from themi.core.travel import TravelHeadsUps
    from themi.core.triage import EmailTriage
    from themi.core.vacuum import Vacuum
    from themi.core.web_recipes import WebRecipes
    from themi.core.web_search import WebSearch
    from themi.core.which_list import WhichList

memory: Key[Memory] = Key("Memory")
taskboard: Key[TaskBoard] = Key("TaskBoard")
habits: Key[HabitReserve] = Key("HabitReserve")
google: Key[GoogleAccounts] = Key("GoogleAccounts")
gmail: Key[GmailSync] = Key("GmailSync")
calendar: Key[CalendarSync] = Key("CalendarSync")
calendars: Key[CalendarBusy] = Key("CalendarBusy")
calendar_copies: Key[CalendarCopies] = Key("CalendarCopies")
day_summary: Key[DaySummary] = Key("DaySummary")
events: Key[Events] = Key("Events")
travel: Key[TravelHeadsUps] = Key("TravelHeadsUps")
task_blocks: Key[TaskBlocks] = Key("TaskBlocks")
wall_routines: Key[CozylaRoutines] = Key("CozylaRoutines")
senders: Key[SenderSuggestions] = Key("SenderSuggestions")
email_audit: Key[EmailAudit] = Key("EmailAudit")
triage: Key[EmailTriage] = Key("EmailTriage")
noise: Key[NoiseDigest] = Key("NoiseDigest")
expected: Key[ExpectedEmails] = Key("ExpectedEmails")
feedback: Key[FeedbackChat] = Key("FeedbackChat")
groceries: Key[GroceryList] = Key("GroceryList")
pantry: Key[Pantry] = Key("Pantry")
meals: Key[Meals] = Key("Meals")
calls: Key[VendorCalls] = Key("VendorCalls")
wall: Key[CozylaTodos] = Key("CozylaTodos")
chart_queue: Key[ChartQueue] = Key("ChartQueue")
lists: Key[Lists] = Key("Lists")
buying: Key[ThingsToBuy] = Key("ThingsToBuy")
spending: Key[Spending] = Key("Spending")
safeway: Key[SafewayCart] = Key("SafewayCart")
breaks: Key[Breaks] = Key("Breaks")
body_double: Key[BodyDouble] = Key("BodyDouble")
music: Key[Music] = Key("Music")
burnout: Key[Burnout] = Key("Burnout")
web_search: Key[WebSearch] = Key("WebSearch")
business_hours: Key[BusinessHours] = Key("BusinessHours")
guides: Key[Guides] = Key("Guides")
recipes: Key[Recipes] = Key("Recipes")
recipe_groceries: Key[RecipeGroceries] = Key("RecipeGroceries")
cooking: Key[Cooking] = Key("Cooking")
web_recipes: Key[WebRecipes] = Key("WebRecipes")
cookbook_save: Key[CookbookSave] = Key("CookbookSave")
recipe_ideas: Key[RecipeIdeas] = Key("RecipeIdeas")
taking: Key[Taking] = Key("Taking")
conversation: Key[ConversationMode] = Key("ConversationMode")
focus: Key[Focus] = Key("Focus")
which_list: Key[WhichList] = Key("WhichList")
follow_ups: Key[FollowUps] = Key("FollowUps")
home_connect: Key[HomeConnectAccount] = Key("HomeConnectAccount")
dishwasher: Key[Dishwasher] = Key("Dishwasher")
thinq: Key[ThinqWatcher] = Key("ThinqWatcher")
laundry: Key[Laundry] = Key("Laundry")
maintenance: Key[Maintenance] = Key("Maintenance")
appliances: Key[Appliances] = Key("Appliances")
roborock: Key[RoborockWatcher] = Key("RoborockWatcher")
vacuum: Key[Vacuum] = Key("Vacuum")
tuya: Key[TuyaWatcher] = Key("TuyaWatcher")
feeders: Key[Feeders] = Key("Feeders")
catgenie: Key[CatGenieWatcher] = Key("CatGenieWatcher")
litter_box: Key[LitterBox] = Key("LitterBox")
reactions: Key[Reactions] = Key("Reactions")
journal: Key[Journal] = Key("Journal")
google_tasks: Key[GoogleTasksInbox] = Key("GoogleTasksInbox")
routines: Key[Routines] = Key("Routines")
liaison: Key[Liaison] = Key("Liaison")
