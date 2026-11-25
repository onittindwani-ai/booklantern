# Business basics check

Software does not fix a business that has no bookkeeping habits. Before you set Booklantern up for a client, check these with them. The longer guide is in the Sendora AI Systems hub, `00-BUSINESS-BASICS.md`.

| Question | Why it matters here |
| --- | --- |
| Do they keep their books in one place (QuickBooks, Xero, Akaunting or a spreadsheet)? | Booklantern drafts entries for that place. It does not replace it. |
| Is there one mailbox where vendors send bills? | The reader only looks at one mailbox. |
| Does a person own the bank statement download every week? | Reconciliation starts from a CSV file. |
| Who approves a bill, and who may approve their own? | A bill that has (or had) a blocking finding needs two people: whoever edited it or closed the finding cannot approve it, and an approver cannot close a finding on their own edit. Editing the finding away does not undo it: the bill remembers that it ever had one. The owner may do both on their own work with a written reason (at least 12 characters in 2 words, not a single letter repeated), and it is logged. A bill with no blocking finding can be approved by one person. Reminders are approved by a person before they are sent. See `13-SECURITY-AND-DATA.md`. |
| What are their payment terms with customers and with vendors? | The ladder and the forecast depend on them. The decided defaults are net 30 and the ladder in `14-LIMITS-AND-HONEST-NOTES.md`. |
| Does their accountant know about this tool? | The accountant owns the books. Booklantern gives no tax or accounting advice. |
| What currency do they use, and do they pay any bills in another one? | Other currencies need a manual exchange rate that you enter by date (see `10-USING-IT-FOR-A-CLIENT.md`). The demo uses one fictional euro rate. |

If most answers are "no", fix the habit first and install the tool later.
