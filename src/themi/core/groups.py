"""Tool groups (CR8b): which tools go together, and the words that call for them.

A message gets the core tools and the groups its words (or the last few messages') call
for; `more_tools` brings in another mid-turn (P1, F33b). Each module registers the groups
its tools are in (`Module.tool_groups`), so a group without its modules isn't offered.
The settings group is the core's (`themi.core.tools.SETTINGS`).

Examples are for the embedding router (P7a): written fresh, never a routing case and never
the family's own words. The order is the order groups are offered in.
"""

from __future__ import annotations

from themi.core.tools import ToolGroup

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


# CR21b: the routines' tools are in this group too; the standard modules call it this.
ROUTINES = WALL
