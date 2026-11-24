# Troubleshooting

| What you see | What to do |
| --- | --- |
| The page says "Could not reach the server" | The API is not running or `API_BASE_URL` is wrong. Open `http://127.0.0.1:8000/health`. |
| Sign in fails five times fast | There is a limit on quick sign ins. Wait a minute. |
| Every page is empty | Demo mode loads the made up company only when the database is empty. Open the search (Cmd+K), choose Reset the demo data, or in a real install import your data. |
| "Post as a draft" says nothing was posted | Correct in draft mode. It needs `MODE=live`, `ACCOUNTING_WRITE=true` and an approved bill. |
| A bill shows "Could not read it" | The file is a scan or picture. Key the fields by hand, or use the live reader once it is tested. |
| A field has no box on the page | The reader found the value but not its place. Read the page yourself. |
| Reminders are not sent | In draft mode they are saved on the Drafts tab. Check Pause all is off, and the invoice has no dispute, promise or opt out. |
| `make check-env` lists a group as half filled | You started a group such as QuickBooks and left a name empty. Fill it or clear the group. |
| `doctor --live` shows FAIL for an adapter | The message after FAIL is the vendor's own. A missing value is listed by name. |
| Vercel build cannot find `ui-kit` | See `06-DEPLOY-VERCEL.md` step 4 and `pnpm-workspace.yaml`. |
| A change on the web app is refused | The request lacked the required header. Use the web app, not a hand made request. |
| The bank import says a line was skipped | Lines already imported (same date, text and amount) are skipped on purpose. |

Still stuck: read the Audit log for the last action, then `docker compose logs api worker` or the terminal where the API runs.
