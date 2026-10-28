# Decisions

Owner rulings, verbatim, in the order given. Chat is the ruling; this file records it.

## 2026-10-28

- "This is a public repo. So ensure no creds leak."
- "I want this as a simple app where anyone can clone the repo and run it to get it running with little to no dependencies."
- "Tasks can be added and stuff reordered at any time. Anything marked done will be added into the database as done with the date. You can generate year end reports."
- "Look at the entirety of the book and put it's key principles into this app."
- "This is to be used by anyone, no internet connectivity. no telemetry. NOTHING."
- "Build on opus and sonnet. You are on fable to work out the shape."
- "ALso the lightness is so anyone in any corporate env with no tools can run this without any dependencies."
- "Book principles is fable level."
- Stack: "B: Python stdlib server + HTML + SQLite"
  (chosen over a single HTML file; the one requirement is therefore Python 3, standard library only)
- List shape: "B: Open → Closed (10) → Focus (3)"

## Parked for the owner (morning of 2026-10-28)

- Open cap default of 20: confirm or change (Settings, 5 to 200).
- Aging counts from creation (or the last Renew), not from the moment an item entered Open. An old item demoted from Closed shows as aging at once. Confirm or change.
- The let-go and set-aside reason prompts are plain browser prompts; a styled dialog is a possible follow-up.

## 2026-10-28, later

- "use only css and html obviously to make the UI extremely appealing."
  (no UI frameworks, icon libraries or CSS libraries; hand-written HTML, CSS and plain JS; the look is a first-class requirement)
- "Allow easily checking a box to mark something as done."
  (every task row in Open, Closed and Focus carries a checkbox; one click marks it done)
- "Also add a dot based calendar shows how much of your 4000 weeks is already done if the person sets their birthday."
- "Also show the 3 focus items much clearer than anything else."
  (Focus becomes a hero band across the top of the page; Open and Closed sit below it, visibly quieter)

## Manager calls (small, reported)

- Weeks nav item is always visible; without a birth date the page is one sentence linking to Settings. The spec's earlier wording was self-contradictory.
- Dropped the "days touched per project" line from PRINCIPLES.md; it was never specified and edges toward streak-counting.
- Writes require `Content-Type: application/json` and reject cross-site `Origin` / `Sec-Fetch-Site`, so a hostile web page in the same browser cannot post to the local server.
- CSV cells starting with `= + - @` are prefixed with a quote and the file carries a UTF-8 BOM, for Excel users.

## 2026-10-28, v2 rulings

- "Move the add thing to a plus icon and a pop up."
- "Give me easy icons to promote and demote stuff. Moving around can be drag and drop."
- "Done stuff to bottom of page."
- "Focus" / "Then next is Closed."
- "Open items is a separate page."
- "At creation let me select what bucket something needs to be in. This applies any time I promote or demote something."
- "If I select focus and focus is full, let me bump something off. THe bumped off item will now be first in closed. Give me a small warning. The last item in closed moves to first item in open."
- "If I select open and open is full ask me what position it should oocupy and move stuff down and same thing, bump the last item out."
- "If something is in open for longer than 2 weeks, it shows up in neglect. And I can retire it."
- "Show the weeks stuff clearer at the top."
- "Colors are boring. Make the webpage pleasing to look at and cool. Have a dark and light mode. Let fable go wild. No outside libraries."

Manager calls under these rulings (small, reported):
- Open gets a cap because "open is full" needs one. Default 20, editable in Settings since no number was ruled.
- An item bumped out of the bottom of Open goes to the Neglect page with the reason "Bumped out of Open", so nothing is lost.
- Moving into a full Closed list is automatic: the item takes first place and the last Closed item becomes first in Open, with the same small warning.
- The one-step-at-a-time promotion rule is dropped: any bucket can be chosen at creation or on any move.
- Stale threshold becomes 14 days. A "Renew" action resets the clock without faking the creation date.
- Theme toggle (system, light, dark) is remembered in the browser only.

## 2026-10-28, morning

- On "dropping onto a full Closed always lands at the top": "No. If I drop lower, move stuff down from that point and kick the last item into open."
  (any placement into a full Closed list honours the given position; later items shift down; the last Closed item moves to the top of Open)
- "Deploy an opus agent to check every line of code for any PII/secrets/confidential info, if none is found push to main."
  (commit and push to main authorized, conditional on a clean audit)

- License: "MIT" (asked which license, given "I don't mind anyone using this for any purpose"). LICENSE file added, copyright holder is the GitHub handle.
