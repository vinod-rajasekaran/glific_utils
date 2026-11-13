# Flow map spec

This is the written spec for the flow-map page. It is phrased as a prompt, but it is **implemented in Python** by `render_architecture.py` — running the scripts calls no LLM and needs no API key. The spec is kept as documentation, and as an alternative way to build the page by hand by pasting it into an LLM with the two JSON files. The two are kept in sync by convention.

The settings map to options of `build_flow_architecture.py`:

| Setting | Option | Environment variable |
|---|---|---|
| Project name | `--project` | `GLIFIC_PROJECT` |
| Tag to start from | `--tag` | `GLIFIC_TAG` |
| Display timezone | `--tz` (`"IST, UTC+5:30"` or an IANA name such as `Asia/Kolkata`) | `GLIFIC_TZ` |
| Today's date | `--date YYYY-MM-DD` (default: today) | |
| Layout | `--layout columns`, `lanes`, `graph` or `all` | `GLIFIC_LAYOUT` |
| Footer line | `--footer` | |
| Context notes | `--notes FILE` (see the README for the format) | |

The prompt also works on its own: paste it into Claude with the two JSON files attached.

---

Role and goal
You are building a flow map for a Glific chatbot from two JSON exports: a flows export and a triggers export. The result is one self-contained HTML page that shows when each flow starts, which flows start which, and what each flow does in plain words: what it sends, sets, moves between groups, logs and alerts. Read every link and number from the files. Do not rely on flow names or memory for any of them.

Settings (fill in before use)
Project name: [PROJECT NAME]
Tag to start from: [TAG, for example 2025 Pilot]
Display timezone: [for example IST, UTC+5:30]
Today's date: [DATE]
Footer line: [one sentence for the footer, or none]
Context notes: [optional, for example how onboarding and content work today]

Inputs
flows.json is a list of flow objects. Each has name, id, uuid, keywords, isActive, a tag object with a label, versionNumber, lastPublishedAt and nodes. Each node has actions, an optional router with categories and cases, and exits with a destination_uuid. triggers.json is a list of trigger objects. Each has the flow it starts (name and uuid), isActive, frequency, groups, days, hours, startAt, endDate and a readable schedule string. Trigger times are in UTC.

Check the inputs first
Hash the files. If two uploads are identical, say so and use one. If flows.json holds only metadata (name, id, keywords, uuid, version, publish dates) and no nodes, stop. Tell me that links cannot be derived from it, and ask me to export the full flow definitions, ideally filtered by the tag. Join flows and triggers on uuid, never on name. List triggers whose flow is missing from the flows file, and flows named in enter_flow actions that are missing from the file.

Scope
Start with the flows that carry the tag. Add every flow they start through enter_flow and mark those "not tagged" when they lack the tag. Add flows that active triggers target even when they lack the tag. Then take one step back: add every flow in the account that starts a flow in scope, mark it as outside the tag, and do not follow its other starts. Put tagged flows that nothing calls and no trigger starts in a strip below the map. Report name-based guesses, such as a shared name prefix, in a tagging gaps note labelled as guesses, and draw no links for them.

What to extract
Use code to parse the files. Print the intermediate tables and check them before you write the page.

Links. Draw a solid link for every enter_flow action and count how many times each caller enters each flow. Draw a dashed data link when one flow writes a contact field with set_contact_field and another flow reads that field in a router operand, and only when one or two flows write it. Mention other shared fields in a note.

Reachability. For each flow, walk from the first node and list nodes that no path reaches. If an unreachable node holds a send, a broadcast or a webhook, say so on the card, for example: holds a staff template that no path reaches, so it never sends.

Per flow summary. Write rows with these labels. Calls: webhooks, described by host and purpose, never by full URL, headers or tokens. Sends: messages and templates by purpose and template name, never full bodies. Sets: contact fields. Moves: group additions and removals, with the group names and the condition that decides them. Logs: sheet reads and writes, by sheet and tab. Alerts: templates sent to staff, by template name and the number of staff contacts. Routes: what the main routers branch on. Counts, Labels, Ticket (topic and assignment, without names), Starts, Feeds, Used by and Note. Keep each row under 25 words and use plain words.

Triggers. For every active trigger give the schedule in plain words, converted to the display timezone with the UTC time in brackets, the group it targets, and the window from startAt to endDate. Cross-check day numbers and times against the schedule string and prefer that string when they disagree. Treat a trigger with no repeat as one-off. Call a trigger active only when isActive is true and the end date has not passed. For inactive triggers write one "Earlier runs" summary for each flow with counts, date ranges and target groups. Add keyword triggers from the keywords field of each flow and list every spelling.

Page design
Write one HTML file with inline CSS and JavaScript. The only external resource is the Google Fonts stylesheet for Bricolage Grotesque (headings) and Atkinson Hyperlegible (body), with fallback font stacks. Build light and dark themes from CSS variables, with a prefers-color-scheme dark override. Set the viewport meta tag with viewport-fit=cover and pad the root with the safe-area insets.

Flow map layout. Use a grid with four columns. When it starts holds trigger cards. Entry flows holds flows that have a trigger or keyword and that no other flow in scope enters. Pilot journey holds flows that an entry flow enters and that route onward. Shared flows holds flows that two or more flows enter. Put each trigger card in the same row as its flow. If I ask for the lane layout instead, give each journey its own horizontal lane under a full-width heading: a journey is the entry flows that reach the same flows through starts or data links, plus everything they reach. Columns then become When it starts, Entry flows and one column per step, with each flow placed one column after the longest chain of starts that leads to it. Put a flow that starts nothing and is entered from more than one journey in a Shared flows lane at the bottom, and flows with no links in a last lane. If I ask for the graph layout, draw each flow and trigger as a small box instead of a card, laid out left to right in layers, with each flow one layer after the longest chain of starts or data links that leads to it and each trigger just before its flow. Route long edges through the gaps between boxes, label edges with the number of starts or the fields handed over, show in one line on each box what the flow does, and open the full card in a side panel when a box is selected. Put every flow in scope that has a link, a trigger or a keyword on the graph, show the tag of each flow that lacks the tag, and put a grey "No start found" box before a flow that no trigger, keyword or flow in the export starts. Give each group that an active schedule on the graph sends to its own box in the first column when some flow adds contacts to it or removes them, draw arrows from the group to its schedules and faint arrows back from each flow that fills or empties it, and add flows outside the scope that add contacts to such a group. Cards are white with a header band that shows the flow name and a pill for the tag, drawn as "No tag" with a dashed outline when the flow is untagged. Trigger cards use an amber header and an Active or Inactive pill. Card rows use a narrow label column and a text column. Moves labels are amber and Alerts labels are red. Cap the map at about 14 cards and move the rest to the strip.

Wires. Draw wires in an SVG overlay behind the cards and compute them in JavaScript from card positions. Use cubic curves between columns and straight vertical lines inside a column. Spread several wires that leave or enter one card across different heights. Solid lines mean starts, dashed lines mean data links, and both carry arrowheads. Redraw on resize, on font load and when a tab becomes visible. On hover or keyboard focus of a card, highlight its wires and dim the other cards. Below 1100 pixels hide the wires and keep the Starts rows in the cards so the links stay readable. Between 700 and 1099 pixels use two columns, and below that one column.

Other sections. Under the map add a short note about shared resources that connect flows without a line: webhook hosts, groups and sheets that several flows use. Add a strip of cards for tagged flows with no link and for untagged flows that matter. Add a card for flows named in the triggers file but missing from the flows file, and a Tagging gaps paragraph. If I give context notes about onboarding or content, add a journey strip of small boxes (field people amber, data systems grey, chatbot messages green) and a Content and data card. Add future or design tabs only when I supply design notes, and never invent a future design.

Page text rules
Write in plain words at the level of an informed senior professional. Use full sentences. Do not use em dashes, bullet lists, numbered lists, paired contrasts, or the words leverage, unlock, seamless, robust and ecosystem. Use tables only for structured data. Headings describe the section and do not editorialise. Body text is 15 pixels, card and table text 13 to 14 pixels, and headings 19 pixels or larger. Use typographic apostrophes and quotation marks in visible text. Add the footer line if I gave one.

Privacy
Never print header values, tokens, API keys, phone numbers or contact names found in the files. Refer to staff contacts by count and to endpoints by host and purpose.

Checks before you finish
Confirm every number and date on the page against the parsed tables. Confirm each solid link exists as an enter_flow action. Check that the HTML tags balance, run node --check on the script and confirm the page has no em dashes. If you can open a browser, check that the wires land on the cards.

Delivery and reply
Publish the page as an artifact if you can, and otherwise give me the HTML file. In the reply, lead with the link or file. Then give the findings in one short paragraph: unreachable nodes, flows missing from the export, tagging gaps, triggers that look wrong, and anything you could not verify. End with one next step I can finish in under ten minutes.
