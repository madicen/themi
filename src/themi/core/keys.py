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
    from themi.standard.breaks import Breaks
    from themi.standard.burnout import Burnout
    from themi.standard.business_hours import BusinessHours
    from themi.standard.conversation_mode import ConversationMode
    from themi.standard.day_summary import DaySummary
    from themi.standard.feedback import FeedbackChat
    from themi.standard.focus import Focus
    from themi.standard.follow_ups import FollowUps
    from themi.standard.guides import Guides
    from themi.standard.habits import HabitReserve
    from themi.standard.journal import Journal
    from themi.standard.lists import Lists
    from themi.standard.memory import Memory
    from themi.standard.reactions import Reactions
    from themi.standard.routines import Routines
    from themi.standard.taking import Taking
    from themi.standard.tasks import TaskBoard
    from themi.standard.web_search import WebSearch
    from themi_google.calendar_copies import CalendarCopies
    from themi_google.connectors.gcal import CalendarSync
    from themi_google.connectors.gcal.busy import CalendarBusy
    from themi_google.connectors.gmail import GmailSync
    from themi_google.connectors.google import GoogleAccounts
    from themi_google.email_audit import EmailAudit
    from themi_google.events import Events
    from themi_google.expected import ExpectedEmails
    from themi_google.google_tasks import GoogleTasksInbox
    from themi_google.noise_digest import NoiseDigest
    from themi_google.senders import SenderSuggestions
    from themi_google.task_blocks import TaskBlocks
    from themi_google.travel import TravelHeadsUps
    from themi_google.triage import EmailTriage
    from themi_home.appliances import Appliances
    from themi_home.body_double import BodyDouble
    from themi_home.buying import ThingsToBuy
    from themi_home.calls import VendorCalls
    from themi_home.chore_chart import ChartQueue
    from themi_home.connectors.catgenie import CatGenieWatcher
    from themi_home.connectors.homeconnect import HomeConnectAccount
    from themi_home.connectors.roborock import RoborockWatcher
    from themi_home.connectors.thinq import ThinqWatcher
    from themi_home.connectors.tuya import TuyaWatcher
    from themi_home.cookbook_save import CookbookSave
    from themi_home.cooking import Cooking
    from themi_home.cozyla_routines import CozylaRoutines
    from themi_home.cozyla_todos import CozylaTodos
    from themi_home.dishwasher import Dishwasher
    from themi_home.feeders import Feeders
    from themi_home.groceries import GroceryList
    from themi_home.laundry import Laundry
    from themi_home.liaison import Liaison
    from themi_home.litter_box import LitterBox
    from themi_home.maintenance import Maintenance
    from themi_home.meals import Meals
    from themi_home.music import Music
    from themi_home.pantry import Pantry
    from themi_home.recipe_groceries import RecipeGroceries
    from themi_home.recipe_ideas import RecipeIdeas
    from themi_home.recipes import Recipes
    from themi_home.safeway import SafewayCart
    from themi_home.spending import Spending
    from themi_home.vacuum import Vacuum
    from themi_home.web_recipes import WebRecipes
    from themi_home.which_list import WhichList

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
