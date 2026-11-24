# Design notes

Written before the interface was built. It follows the shared kit's look (warm cream and coffee, one accent) and records the choices that are specific to Booklantern.

## Who looks at this screen

A small business owner or the person they trust with the books, once or twice a day, with a coffee. They are not accountants and they are worried about two things: running out of cash, and paying or chasing the wrong thing. So the first screen answers "will we be fine for three months" and every other screen answers "what needs me today".

## Palette (60, 30, 10)

- 60 percent warm neutrals: cream, oat, sand (the kit's light surfaces). Dark theme "espresso" uses the same hierarchy.
- 30 percent coffee browns for text, rules and chart axes.
- 10 percent accent: **sage** (`#4f6b4d` light, `#9cc096` dark). Sage reads as calm and money without the shout of a bright green, and the other systems in this family use different accents. It marks the forecast line, selected rows, the primary button and a confirmed match.
- True red only for real alarms: a blocking finding, cash below zero, a bank account that changed. Amber (the kit's warning) for things to look at. The forecast area below zero turns red, so danger is never only a colour (the week label and the low point text say it too).

## Type and numbers

Geist for the interface and every figure, Instrument Serif for page titles and the big cash figure. Tabular figures everywhere a number can change. Money always shows its currency symbol and two decimals, right aligned in tables, never truncated. Dates are absolute after a week. Type steps follow the kit (13, 16, 21, 27, 34, 55, 89) and spacing is 8, 13, 21, 34, 55.

## Motion

The kit's easing and durations (press 140 ms, hover 180 ms, sheet 320 ms, page 300 ms, chart draw 700 ms once). Two additions for the signature screens, both animating only transform and opacity or an SVG path value tweened in script:

- **Forecast chart tween.** When the slider changes the answer, the line and area move from the old values to the new ones over 420 ms (ease out), using one animation frame loop that is cancelled when a newer answer arrives. Reduced motion jumps straight to the new values.
- **Highlight link on the review page.** Hovering or focusing a field fades the matching box on the page in over 160 ms and scrolls the page container to it if it is out of view. Hovering a box focuses its field. Reduced motion removes the scroll animation and keeps the highlight.

## Signature interactions

1. **Invoice review.** The page picture is on the left (38 to 62 split on desktop, stacked on a phone with the page first). The extracted fields are on the right, each with a label, the value as an editable input, a confidence chip (a number from 0 to 100 and a word: sure, check, unsure) and a "why" line that lists the rules behind the number. A field with no box on the page (typed by hand, or from a scan) says so. Boxes are drawn as fractions of the page so the overlay scales at any width. Findings from the code checks sit above the fields as plain sentences. Approve needs a written reason when a blocking finding is open. Post as draft says plainly when draft mode means nothing was posted.
2. **Cash cockpit.** The 13 week chart with three sliders: collect customers N days later, pay vendors N days later, add a hire at an amount per month from a week. The numbers on screen (closing cash, lowest point, week cash runs out) count to the new values. The base forecast stays as a dashed line behind the scenario so the difference is the picture. The answer comes from the same code that makes the real forecast (the API), so nothing on screen is computed twice in two ways.

## Pages and what each one is for

| Page | Job | Key interaction |
| --- | --- | --- |
| Cash cockpit | will we be fine | sliders, dashed base line, written explanation labelled with who wrote it |
| Invoice review | is this bill right | linked highlights, per field edit, confidence chips |
| Bills and payables | what do we owe and what is waiting | table with finding chips, filter by state, open the review |
| Aging | who owes us and how late | stacked bars, click a bar or segment to drill down into invoices |
| Collections | who do we chase and how | ladder timeline per invoice, promise and dispute actions, approve drafts |
| Reconciliation | does the bank match the books | two columns, drag a line to an item or press L then pick, confidence on every suggestion |
| Exceptions | things a person must look at | one list, severity, resolve |
| Reports | month end | numbers, PDF download |
| Integrations | connect tools | adapter list, test button, tiers and verified state |
| Approvals | decisions waiting | approve or reject with a note |
| Audit log | what happened | hash chain check |

## Micro interactions from the catalogue that matter here

Buttons show a spinner then a tick on every action. Numbers count up on change. Tables are virtualized (5,000 bank lines stay light), sortable, with j, k, enter keyboard use. A drag has a lift, a gap and a settle; the same link can be made with the keyboard (focus a bank line, press L, choose the item, press enter). Toasts have undo where the action can be undone (unlink, resolve). Empty states offer the next action. Errors say what happened and how to fix it. The command palette (Cmd or Ctrl plus K) reaches every page and the demo actions.

## Edge cases we designed for

A scan with no text layer (says so and offers manual entry), a bill with no vendor match, an amount in a second currency (shown in its own currency with the converted amount, the rate and its date beside it, or a no rate flag), a bank file that is not a CSV, the same file twice, a part payment, a split deposit, cash that runs out in week 1, a forecast with nothing receivable, kill switch on, draft mode, slow network.

## Accessibility

Contrast is checked by the kit's test and by axe in light and dark. Every colour state also has a word or icon. Focus rings are never removed. The page picture has alt text naming the document. Boxes are decoration for sighted users; the same information is in the field list. The drag link has a keyboard path. Reduced motion keeps fades and removes movement.
