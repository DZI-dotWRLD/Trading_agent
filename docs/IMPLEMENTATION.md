# Implementing the trading-update agent at VSCP

This is the technical guide for whoever installs and runs the tool at VSCP: a team member or IT. For a first install, follow the main `README.md`; this guide adds the production details (Microsoft 365, permissions, monitoring, the cloud). For a plain-English overview, see `docs/HOW_IT_WORKS.md`.

`ADR-00nn` references name design decisions recorded in the development repository. They are not needed to run the tool.

Allow about an hour, plus any time IT needs to approve access to the mailbox.

## 1. What runs where

```
 any portfolio company ──email──▶ VSCP mailbox ◀──polls every 5 min── service (python -m agent run)
   (the sender's address decides which company)                        │
          1. saves the source file (add-only) ──────────────────────────┼──▶ shared drive: ROOT/<company>/Trading Updates/<year>/
          2. copies it to a scratch workspace                           │      (synced SharePoint / OneDrive / network folder)
          3. Claude builds the _vClaude output there (sandboxed)        │
          4. validator recalculates and checks every number             │
          5. queues it for review (outside the drive) ──▶ email "Review needed", file attached
                                                                        │
 dashboard (localhost:8501) ── Review queue page: Approve / Reject      │
          6. on Approve: service checks the file is unchanged ──────────┘──▶ publishes output + metrics.json (add-only)
             and emails "Approved and saved"; on Reject: "Rejected, not saved", nothing written
```

It all runs on **one Windows PC**. That PC must be switched on and logged in on Monday mornings.
- **The service** is a long-running Python process. It watches the inbox, runs each weekly job, carries out review decisions, and sends the emails. It's the only part that writes to the drive.
- **The dashboard** is a separate local web page. It reads the reports, and its Review queue page records Approve and Reject decisions. It never writes to the drive and holds no email credentials (ADR-0017).
- **Claude** is called through the Anthropic API. Each weekly run sends that week's workbook to the API (see [Data and privacy](#9-data-and-privacy)).

## 2. Requirements

| Item | Notes |
|---|---|
| Windows 10 or 11 PC | Stays on and logged in over the Monday deadline. A VM or a small always-on desktop is ideal. |
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.12 and every dependency into `.venv`. No admin rights needed. |
| LibreOffice **or** Microsoft Excel | Needed to recalculate workbooks before validation. LibreOffice is preferred; the tool uses Excel through COM if LibreOffice isn't installed. |
| Anthropic API key | From console.anthropic.com. Set a monthly spend limit there. A normal week costs about $1. |
| A mailbox the service can read and send from | Gmail or Microsoft 365. See [section 5](#5-connect-a-mailbox). |
| The shared drive, available as a local folder | For example SharePoint synced through OneDrive, or a mapped network drive. See [section 4](#4-connect-the-shared-drive). |

## 3. Install

```powershell
git clone <repo> C:\VSCP_trading_agent      # or download the ZIP from GitHub and unzip it there
cd C:\VSCP_trading_agent
.\setup.ps1
```

`setup.ps1` does four things:
- installs dependencies with `uv sync`
- checks for LibreOffice or Excel
- creates `.env` from `.env.example` if it doesn't exist
- runs `python -m agent check`

To do the same by hand:

```powershell
uv sync
Copy-Item .env.example .env
.venv\Scripts\Activate.ps1
python -m agent check
```

Then fill in `.env`. It holds the only secrets, and it must never be committed or shared:

```ini
ANTHROPIC_API_KEY=sk-ant-...
MAIL_USER=trading-updates@vscpllc.com
MAIL_APP_PASSWORD=...          # IMAP only; see section 5
```

Restrict `.env` to the account that runs the service:
- right-click the file, then **Properties > Security**
- remove everyone except that account and Administrators.

## 4. Connect the shared drive

Everything the service needs about the drive is in two lines of `config.yaml` (ADR-0004):

```yaml
root: "C:/Users/<svc-account>/Vesey Street Capital/Portfolio - Documents"   # the synced library, as a local path
path_template: "{root}/{company}/Trading Updates/{year}"
```

- **`root`** is the top of the portfolio library, as a local path. It can be a OneDrive-synced SharePoint library, a mapped drive (`P:/Portfolio`) or a UNC path (`//fileserver/Portfolio`).
- **`path_template`** is where a company's weekly files live under `root`.
  - `{company}` is the company's folder name: the `key` in `companies/<name>.yaml`.
  - `{year}` is the ISO year of the report.
  - Change the template to match VSCP's existing layout, for example `"{root}/{company}/Reporting/Weekly/{year}"`.

`python -m agent check` prints the folder it resolved for each company. Make sure it's the folder where VSCP already saves the trading updates. The service creates the year folder if it's missing, but never anything above it.

**How the tool treats the drive:**
- **It only adds files.** The source is saved as `Trading_update_CW38_2026.xlsx`, and a resend with different content becomes `..._r2.xlsx`. The output is saved as `..._vClaude.xlsx` next to the source, along with a small `.metrics.json`. Nothing is ever overwritten or deleted (ADR-0013).
- **Prior weeks are read from the same folder.** Last week's source gives the W/W comparison, and last week's `_vClaude` output gives the opening loan balance. Keep earlier weeks in that folder, named as Inceptua sends them.
- **Claude never sees the drive.** It works on copies in `runs_dir`, which must be **outside** `root`. The service refuses to start otherwise (ADR-0009).
- **Every run is checked for tampering.** The service snapshots the drive before and after each run. A change in the company's own folder fails the run; a change elsewhere only warns (ADR-0016).

**First run at VSCP.** If the folder has no earlier `_vClaude` output, the tool has nothing to carry the opening loan balance forward from. Set it once in `companies/inceptua.yaml`:

```yaml
assumptions:
  opening_loan_balance_eur: 12465873.39   # the "Loans - BoP" value from the last output you trust
```

Remove the line after the first successful run. From then on the balance carries forward automatically from last week's output.

**OneDrive sync.** Make sure the report folder is set to **Always keep on this device**. Otherwise the prior weeks may be cloud-only placeholders when the service reads them.

## 5. Connect a mailbox

The service reads new mail and never marks it read, moves it or deletes it. It sends from the same account. Which messages count is set per company in `companies/<name>.yaml` (ADR-0008). A message must pass **both** checks:

```yaml
senders:                                   # only these addresses are accepted (must not be empty)
  - finance@inceptua.com
filename_pattern: 'Trading_update_CW\d{2}_\d{4}(_r\d+)?\.xlsx'
```

Who gets told is set in `config.yaml`:

```yaml
notify:
  to: [analyst@vscpllc.com, associate@vscpllc.com]
dashboard_url: "http://localhost:8501"     # linked from the "ready" email; empty = no link
```

### 5a. Gmail or another IMAP provider (the tested path)

```yaml
mailbox:
  type: imap
  imap_host: imap.gmail.com
  smtp_host: smtp.gmail.com                # SMTP over implicit TLS, port 465
  user_env: MAIL_USER
  password_env: MAIL_APP_PASSWORD
  lookback_days: 7
```

1. Turn on 2-step verification for the account.
2. Go to **Google Account > Security > App passwords**, create an app password, and put it in `.env` as `MAIL_APP_PASSWORD`.
3. Run `python -m agent poll-once`. It checks the inbox once and logs what it would do with each message.

A dedicated address, such as `vscp.trading.updates@gmail.com`, is better than a personal one. Have Inceptua send to it, or add a forwarding rule from the team inbox.

### 5b. Microsoft 365 (the likely setup at VSCP)

Microsoft 365 has largely retired password ("basic") login for IMAP and SMTP. So the IMAP adapter above, which logs in with a password, will usually be refused. There are two ways forward:

**Option 1: forward to a dedicated inbox. No code, and it works today.**
- Create an Exchange mail-flow rule that copies messages matching the sender and the attachment name to a dedicated Gmail or IMAP inbox, and use 5a.
- Notifications then come from that inbox. That's acceptable for a pilot, less so long term.

**Option 2: the Microsoft Graph adapter (`agent/mail/graph.py`). Recommended for production.**

`GraphMailbox` implements the same two methods as the IMAP adapter (`fetch_new`, `send`), so nothing else in the pipeline changes. It signs in as an app (client credentials), not as a person, and uses only the Python standard library.

- **Reading:** it lists the inbox for the last `lookback_days` and downloads the file attachments of messages it hasn't processed. It only ever sends GET requests, so it never marks a message read, moves it or deletes it. An attached email or a OneDrive link is skipped, so the company must attach the workbook itself.
- **Sending:** it uses `sendMail`, from the same mailbox, saved to Sent Items. That call is limited to about 4 MB. A bigger attachment would need `Mail.ReadWrite`, so instead it is left off and the email says to open the file from the dashboard's review queue. The reports built so far are 1.2 to 1.8 MB.
- **Errors:** an expired token is renewed once, throttling (429) is retried once, and anything else fails with Microsoft's own error code. Three failed inbox checks in a row raise the usual inbox-health alert.

**What VSCP's IT sets up in Entra ID** (the request to send them is `docs/IT_REQUEST_GRAPH.md`):
1. A dedicated mailbox, for example `trading-updates@vscpllc.com` (a shared mailbox needs no licence).
2. **Register an app** under Entra ID > App registrations, single tenant. Create a client secret (or a certificate, if their policy prefers).
3. Grant `Mail.Read` and `Mail.Send` **limited to that one mailbox**. An unscoped grant covers every mailbox in the tenant. Either:
   - **Exchange Online RBAC for Applications** (recommended): assign the roles `Application Mail.Read` and `Application Mail.Send` with a management scope for that mailbox, and add **no** Entra API permission for them (an Entra grant is tenant-wide and would override the scope); or
   - **Entra admin consent** to the Graph application permissions plus an **Application Access Policy** (`RestrictAccess`) for a group containing that mailbox.

   The exact commands are in `docs/IT_REQUEST_GRAPH.md`.

**Configure it:**

```yaml
# config.yaml
mailbox:
  type: graph
  user_env: MAIL_USER            # the mailbox address
  lookback_days: 7
```

```dotenv
# .env (never config.yaml)
MAIL_USER=trading-updates@vscpllc.com
GRAPH_TENANT_ID=<Directory (tenant) ID>
GRAPH_CLIENT_ID=<Application (client) ID>
GRAPH_CLIENT_SECRET=<client secret value>
```

**Check it:**
1. `python -m agent check` names any missing setting.
2. `python -m agent poll-once` lists what is in the inbox. A `403 ErrorAccessDenied` means the mailbox scoping (step 3) doesn't include this mailbox; `401 invalid_client` means a wrong or expired secret.
3. Send one test file from an allowlisted address and check that the "ready for review" email arrives from the dedicated mailbox.

The adapter has been tested against a simulated Graph service only, not yet against a real Microsoft 365 tenant, so step 2 is the first real test.

## 6. Run it

| Command | What it does |
|---|---|
| `.\start.ps1` | Starts the service in this window, polling every `poll_minutes` (default 5). Stop it with Ctrl+C. |
| `.\start-all.ps1` | Checks the configuration, then starts the service and the dashboard, each in its own minimised window, and opens the dashboard. Anything already running is left alone. `-Config` and `-Port` are passed through. |
| `.\install-autostart.ps1` | Adds a Task Scheduler entry that starts the service at logon and restarts it if it stops (ADR-0012). |
| `.\start-dashboard.ps1` | Starts the dashboard at http://localhost:8501. It only accepts connections from this PC. Its top bar says whether the service is running (from `heartbeat.json` next to `state.json`): running and when the inbox was last checked, which report is being processed, or not running / stopped. |
| `python -m agent poll-once` | One inbox check, then exit. Useful after a config change. |
| `python -m agent process FILE --company Inceptua` | Runs one file by hand into the review queue, for example after fixing a failed or rejected week. Add `--no-email` to print the emails instead of sending them. |
| `python -m agent review list` | Lists outputs waiting for review, and recent decisions. |
| `python -m agent review approve ID --by NAME` | Approves from the command line, the same as the dashboard button. `reject ID --reason TEXT --by NAME` rejects. |

**No deadlines.** The service processes a trading update whenever it arrives; there is no Monday cut-off and no "file not received" alert (ADR-0022). The only automatic alert besides the per-report emails is when the inbox cannot be read 3 checks in a row.

## 7. Day to day

**Reviewing an output**
1. Open the dashboard. The top bar shows **Review queue (n)**, and the Portfolio page lists what is waiting under "Needs attention".
2. Each output shows its automatic check results, the headline numbers, any warnings (including any text in the file that looked like an instruction) and where Claude took each typed-in value from. Download the file to look through it in Excel.
3. Enter your name and click **Approve and publish**, or **Reject** with a reason. Within about 10 seconds the service publishes the file (or records the rejection) and emails the team.

Only the first decision counts. Before publishing, the service checks that the file is byte-for-byte the one that passed validation.

**The emails you'll get** (all to `notify.to` only, never back to the sender)
- **"Review needed: Inceptua Group CW38 2026"**: the output passed validation and is waiting in the review queue. **Nothing is on the drive yet.**
  - The workbook is attached when it's small enough, and the email links to the dashboard.
  - It names any files that changed elsewhere on the drive during the run.
  - A resent week is marked "(revised)".
- **"Approved and saved: ..."**: who approved it, and where it was saved.
- **"Rejected, not saved: ..."**: who rejected it and why, and the command to rebuild it.
- **"ACTION NEEDED: Inceptua CW38 2026 report was not produced"**: nothing was written to the drive.
  - The email gives the reason, the validator's failed checks and the folder with the run's files.
  - A failed build is retried once automatically before this email is sent.
- **"On hold: Meridian Health CW38 2026 is waiting for last week's report"**: the file arrived before last week's report was approved. It runs by itself once that report is approved (or a corrected last week is approved). Nothing to do (ADR-0023).
- **"ACTION NEEDED: the agent cannot read the inbox"**: 3 inbox checks in a row failed (for example a changed password). A follow-up says when it can read it again.

**Where to look**

| File | Contents |
|---|---|
| `data/service.log` | One line per email handled, run started, published and email sent. Rotated at 5 MB; the last 5 files are kept (`service.log.1` … `.5`). |
| `data/state.json` | Which emails were processed, so each one is handled exactly once |
| `data/_runs/<company>/<run>/transcript.jsonl` | Everything Claude did in that run |
| `data/_runs/<company>/<run>/validation.json` | Every check the validator made, passed or failed |
| `data/review/<id>/item.json` | One output in the review queue: checks, warnings, sources, and who decided what and when |

**Common situations**
- **Inceptua resends a corrected file.** It's saved as `_r2` and processed like a new week, and the output is `..._r2_vClaude.xlsx`. The dashboard shows the latest revision.
- **A run failed, or an output was rejected.** Read `validation.json` or the reviewer's reason, fix the cause (usually the source file), and rebuild with `python -m agent process "<path to source>" --company Inceptua`. The new output goes to the review queue again.
- **The same email arrives twice.** It's ignored as a duplicate, including when an earlier copy is still waiting in the queue or was rejected.

## 8. Add another portfolio company

Every portfolio company sends the same trading-update template, so the same skill and validator serve all of them (ADR-0017). Adding a company is configuration only. Copy `company_template/NEW_COMPANY_TEMPLATE.yaml` to `companies/<name>.yaml` and fill in its `CHANGE_ME` values (the main `README.md`, step 6, walks through it). The result looks like this:

```yaml
key: Meridian Health              # its folder name under root
display_name: Meridian Health     # shown in emails and the dashboard
name: Meridian                    # the name inside its workbook's labels, e.g. "Meridian Holdco"
senders:                          # its sending address(es): this is what tells companies apart
  - finance@meridian.com
assumptions:                      # this company's cash-model assumptions
  model_start_date: "2026-06-01"
  po_advance_rate: 1.21
  forward_weeks: 28
  opening_loan_balance_eur: 5000000   # first run only; later weeks carry it forward
panels: [overview, revenue_gp, customers, cash, reports]
# style_template: companies/meridian_style.xlsx   # optional: its own look for the generated tabs (ADR-0021)
```

Then run `.\start.ps1 -Check`. It shows the folder the company's files will be saved to.

- **The sender decides the company.** Every company uses the same file name (`Trading_update_CW##_YYYY.xlsx`), so each sending address must be on exactly one company's list.
- **A new company is safe from its first file.** Its outputs get the full numeric validation and still need a person's approval.
- **A dashboard-only company** (`pipeline: false`, no `senders`) never processes email. It appears in the dashboard dropdown as soon as a `*.metrics.json` exists under its folder. Those files use the generic schema: a `kpis` list of `{key, label, value, unit}`.- **The look of the generated tabs** is VSCP's house style, copied from the sample output, for every company. Giving one company its own look needs a style template made from a hand-formatted output with the development repository's `make_style_template.py`; then set `style_template` as above.
- **A company whose workbook is a different template** would need its own skill and validator. That's a development task, not configuration.

## 9. Data and privacy

- **What reaches Anthropic.** Each run sends that week's source workbook, and last week's files for comparison, to the Anthropic API. Nothing else on the drive is sent, and no email content except the attachment. Check that this fits VSCP's data policy and Anthropic's commercial terms before going live.
- **What doesn't leave the PC.** The dashboard, `metrics.json`, logs and state all stay local.
- **Secrets.** They exist only in `.env`, never in `config.yaml`, logs or emails.

## 10. Hardened production setup

The demo protects the drive with software checks. For production, add operating-system controls as well, so the protection doesn't depend only on the tool's own code (ADR-0016):

1. **A dedicated Windows account** (for example `svc-trading-agent`). Run the service and the scheduled task as this account, not as a person.
2. **Drive permissions for that account.** Allow read on the portfolio library, and create-files on the company report folders only, with **no delete and no modify**.
   - On an NTFS or network share: grant *List folder / Read data* and *Create files / Write data* on the report folders, and deny *Delete* and *Delete subfolders and files*.
   - On SharePoint, where rights are per library: give the account *Contribute* on the report library only, and rely on the library's version history plus the tamper-check email.
3. **API limits.** Set a monthly spend limit on the API key in the Anthropic console. The per-run cap is `agent.max_budget_usd` in `config.yaml` (default $5).
4. **A dedicated mailbox with least privilege.** For Graph, scope the app to that one mailbox (section 5b).
5. **Keep the dashboard local.** It listens on `localhost` only. To share it, put it behind VSCP's sign-in (section 11). Don't open the port.
6. **Protect the review queue.** `review_dir` (default `data\review`) holds unapproved outputs. Limit it, like `.env`, to the service account and the reviewers. A file changed there after validation is refused at approval, so tampering can't publish anything, but the files themselves are confidential.

The agent itself is already confined:
- It runs on copies in a scratch folder.
- File tools reach only inside that folder.
- Bash is limited to `python`, simple copies and a few read-only commands.
- It has no web, network or package installs, no user-level settings and no MCP servers.
- Turns and spend are capped.

A PreToolUse hook enforces all of this and denies any tool not on its allowlist (`agent/claude/hooks/sandbox.py`, ADR-0009).

## 11. Sharing the dashboard with the team

The dashboard listens on `localhost` only, so by default only someone sitting at the service's PC can open it. Its Review queue page publishes reports, so whoever can reach it can approve them. **Never open the port without a sign-in in front of it.**

| Option | Who can open it | Sign-in | Work | When |
|---|---|---|---|---|
| **A. This PC only** (default) | Whoever is logged on to the PC, or connects to it by Remote Desktop | Windows logon | None | Pilot with one or two reviewers |
| **B. Entra application proxy** (recommended) | Anyone VSCP allows, from the office or at home, at an `https://….msappproxy.net` address | Microsoft 365 single sign-on, MFA, Conditional Access | Half a day for IT. No code changes; the dashboard stays on `localhost`. | A team of reviewers |
| **C. Streamlit's own sign-in** | Anyone on the office network | Microsoft Entra ID through Streamlit's built-in OpenID Connect login (`st.login`) | About a day: an Entra app registration, `[auth]` in `.streamlit/secrets.toml`, a login gate in `dashboard/app.py`, HTTPS, and binding to the network address | No application proxy available |

**With B or C, record the signed-in identity.** Today an approval records the name the reviewer types. Behind a sign-in it should record the account instead (`st.user.email` with C; the proxy's identity header with B). That's a small change in `_review_item` in `dashboard/app.py`.

**Who sees what.** Every signed-in user sees every company. If some reviewers may only see some companies, that needs a per-user company list. It's not built.

**Links in emails.** Set `dashboard_url` in `config.yaml` to the address people actually use (for example the proxy address). The "Review needed" email then links straight to the review queue (`?view=review`). Every page has its own link, such as `?view=company&company=Inceptua&week=CW37 2026`.

## 12. Monitoring

**What exists**

| Signal | Where it shows | Who notices |
|---|---|---|
| **Service status:** running, processing, stopped, or not running | The dashboard's top bar, from `heartbeat.json` next to `state.json` (rewritten about every 10 seconds) | Anyone with the dashboard open |
| **Inbox unreachable** 3 checks in a row | "ACTION NEEDED: the agent cannot read the inbox" email | The team |
| **Every run's outcome** | Review needed, ACTION NEEDED, On hold emails; the dashboard's Needs attention list and reporting tracker | The team |
| **Automatic restart** | Task Scheduler restarts the service if it stops (`install-autostart.ps1`) | Nobody needs to |
| **Spend** | Run costs in the dashboard (Files & audit, Review queue); the monthly limit on the API key | Whoever owns the API key |
| **Logs** | `data/service.log`, rotated at 5 MB, last 5 files kept | Support |

**The gap:** if the PC is off, asleep or crashed, the service can't email anyone. The dashboard shows "Service not running", but only to someone who opens it. Weekly reports would quietly stop arriving.

**Closing it (recommended before going live), cheapest first:**
1. **A dead-man's switch.** The service pings an external check URL after each successful inbox check, for example [Healthchecks.io](https://healthchecks.io) (free tier) or Azure Monitor. If no ping arrives for 30 minutes, the check emails or messages the team. This is a few lines in `Service.run_forever` and needs outbound HTTPS from the PC. It's not built, because it sends a signal to a third party.
2. **A Windows check.** A second scheduled task runs every 15 minutes, reads `heartbeat.json`, and emails the team if it's older than 30 minutes. It doesn't catch the whole PC being off, which option 1 does.
3. **On a VM (section 13):** the cloud's own VM health alerts, plus option 1.

**Also worth watching:** the Anthropic usage page (cost per week rising means files are getting larger or runs are retrying) and the number of failed or rejected weeks on the reporting tracker.

## 13. Moving to the cloud

The demo runs on one Windows PC. Three steps lead away from that, each usable on its own:

| Step | What changes | Work | Gain |
|---|---|---|---|
| **1. A cloud VM** (recommended first) | The same install (`setup.ps1`, `install-autostart.ps1`) on an always-on Windows VM, for example Azure B2ms with 8 GB of RAM. The shared drive is reached through OneDrive sync, as on a PC. The dashboard is reached through the application proxy (section 11, option B). | 1 to 3 days | No PC to keep on; the cloud's backup and health alerts |
| **2. Containers** | The service and the dashboard as Linux containers (for example Azure Container Apps). LibreOffice does the recalculation (Excel isn't available). Storage moves behind an interface: SharePoint through Microsoft Graph instead of a synced folder, and `state.json` and the review queue in a database or blob storage. The mailbox moves to Graph (5b). | 1 to 2 weeks; the SharePoint storage layer is most of it | Repeatable deployments, scaling, no Windows to patch |
| **3. Cloud-native** | Event-driven: a Graph mail subscription starts a run instead of polling. Runs become queued jobs; the dashboard and approvals become a web app with Entra sign-in. | 3 to 5 weeks | Several runs in parallel, per-user permissions, audit in the platform |

**What carries over unchanged:** the skill, the validator, the reference model, the sandbox hook, the review and approval rules, and the tests. These don't depend on where the service runs.

**Size the VM for memory, not CPU.** A run loads the workbooks several times and recalculates them in LibreOffice, and on the 8 GB development PC low memory was the only cause of slow or stopped runs. Give the VM 8 GB or more and nothing else to do. Runs happen one at a time.

**Data residency.** Choose the VM's region to match VSCP's data policy. Each run still sends the week's workbook to the Anthropic API, as on the PC (section 9).

## 13a. Speed and cost

**Models.** The weekly build uses **Claude Sonnet 5.5** (`VSCP_MODEL`). On 6 Oct 2026 it passed all 6 eval cases on the first attempt, every check (159/159), at about $0.38 per report against about $0.62 for Opus. Learning a new company's layout uses **Opus 5.5** (`VSCP_DISCOVERY_MODEL`): it happens once per company, and it's the step that needs the most judgement. Both are set in `.env`.

**Where a run's 4-5 minutes go.** Sonnet wasn't faster than Opus. Most of a run is spreadsheet work: loading the workbooks, LibreOffice recalculation in Claude's self-check and again in the final validation, and the checks. With too little free memory the same run takes 12-13 minutes.

**What would make it faster**, in order of value:
1. A dedicated machine or VM with 16 GB and nothing else on it, and 2-3 companies processed in parallel. On a busy Monday this takes 20 companies from about 2 hours to under 1.
2. No second recalculation when Claude's self-check passed on the same file (a hash proves it's unchanged): 1-3 minutes per run.
3. Working copies without pivot-table caches (the originals untouched): every load 8-13x faster.
4. LibreOffice kept running in the background instead of started for each recalculation: 10-30 s each.
5. Instant email pickup (IMAP IDLE or Graph notifications) instead of polling: up to `poll_minutes`.
6. Only if still needed: a tested toolkit the agent calls for the mechanical grid. This is a trade-off, because more of the build would be fixed code rather than the agent's work.

## 14. Go-live checklist

- [ ] `.\setup.ps1` finished and `python -m agent check` shows ✓
- [ ] `root` and `path_template` point at the existing trading-update folder, and the check prints the right path
- [ ] Earlier weeks' files are in that folder and kept on the device, or `opening_loan_balance_eur` is set for the first run
- [ ] Mailbox connected (5a or 5b), and `poll-once` lists the inbox without errors
- [ ] `senders` holds Inceptua's real sending address(es), and `notify.to` holds the team
- [ ] A dry run on a real file: `python -m agent process "<last week's file>" --company Inceptua --no-email` reaches the review queue, and approving it in the dashboard saves it to the right folder
- [ ] Each company's `senders` list is correct, and no address appears under two companies
- [ ] Autostart installed, and the service survives a logoff and logon
- [ ] Spend limit set on the API key
- [ ] Section 10 applied, or consciously deferred for a pilot
- [ ] The reviewers can open the dashboard (section 11), and `dashboard_url` is the address they use
- [ ] Someone is told when the service stops: a dead-man's switch or a heartbeat check (section 12)
