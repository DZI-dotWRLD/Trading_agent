# VSCP Trading-Update Agent

Every week, each portfolio company emails VSCP an Excel "trading update". This agent does the analyst's weekly work on it automatically:

1. It **picks up the email** from a dedicated mailbox and checks it came from a known company.
2. It **saves the file** to that company's folder on the shared drive.
3. **Claude (AI) builds the report**: a copy of the file with four new tabs: Cash Schedule, weekly and monthly Cash Summaries, and a comparison with last week. Every number is a live Excel formula.
4. It **checks every number** against an independent calculation.
5. It **emails the team** "Review needed". A person opens the dashboard and clicks **Approve and publish**.
6. Only then is the report **saved next to the source file** on the shared drive.

> **Nothing is saved to the shared drive until a person approves it.** The agent never runs Excel macros and only emails the addresses you list.

**Want to understand how it works first?** Read [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md): a description, with diagrams, of what it does, what is finished, its limits, and what is needed to turn it into a full product.


## 0. Before you start

You need:

| What | Why | Where to get it |
|---|---|---|
| A **Windows 10 or 11** PC that stays switched on | The agent runs on this PC and checks the mailbox every minute | |
| About **3 GB of free memory** while a report is built | Excel files are large | Close other apps if the PC is slow |
| **Internet access** | To reach the mailbox and Claude | |
| The **shared drive** with the companies' folders, visible on this PC | Where source files and reports are saved | Usually SharePoint synced through OneDrive, e.g. `C:\Users\<you>\Vesey Street Capital\Portfolio - Documents` |
| A **mailbox** that only receives the trading updates | The agent reads every email in it | A new Gmail account works today (step 5). Microsoft 365 needs VSCP's IT first: see [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md), section 3 |
| An **Anthropic account** with some credit | Claude builds the reports | https://console.anthropic.com (step 4). Each report costs about **$0.40–1.00** |

No administrator rights are needed.

### How to type a command (you will do this a few times)

All commands in this guide are typed into **PowerShell**, a window where you type instructions to Windows:

1. Open **File Explorer** and go into the agent's folder (step 1).
2. Click once in the **address bar** at the top (where the folder path is shown), so the path is highlighted.
3. Type `powershell` and press **Enter**. A blue or black window opens, already "inside" the agent's folder.
4. Copy a command from this guide (the grey boxes), click into the PowerShell window, **right-click** to paste it, and press **Enter**.

> **Every time you open a new PowerShell window,** first run this line. It allows this folder's scripts to run, in that window only:
> ```powershell
> Set-ExecutionPolicy -Scope Process Bypass
> ```
> If Windows asks "Do you want to change the execution policy?", type `Y` and press Enter.

### How to edit a settings file

You will edit three small text files. Open each one with **Notepad** by typing in PowerShell, for example:

```powershell
notepad config.yaml
```

Change only what this guide tells you to, then **File > Save** (Ctrl+S) and close Notepad.

- In the `.yaml` files, change only the text **after** a colon `:`. Never change the word before it.
- Keep the **spaces at the start of lines** exactly as they are. They matter.
- Lines starting with `#` are notes for you; the agent ignores them.
- Every value you must change contains the words **`CHANGE_ME`**. The check in step 9 refuses to start the agent while any are left.

---

## 1. Download the agent

1. Open the GitHub link you were sent.
2. Click the green **`<> Code`** button, then **Download ZIP**.
3. Open your **Downloads** folder, right-click the ZIP file, and choose **Extract All…**
4. Extract it to `C:\` so you get a folder like `C:\VSCP_trading_agent-main`.


From now on, "the agent's folder" means `C:\VSCP_trading_agent`.

`git clone <link> C:\VSCP_trading_agent` does the same.

## 2. Install two programs

**uv** installs Python and everything the agent needs, inside the agent's folder only.

1. Open PowerShell (any folder is fine), paste this line, and press Enter:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
2. When it says it's done, **close that PowerShell window**. The next window you open will find uv.

**LibreOffice** (free) recalculates the Excel files so the numbers can be checked. Microsoft Excel also works if it's installed, but LibreOffice is more reliable for an unattended PC.

1. Go to https://www.libreoffice.org/download/ and download the Windows version.
2. Run the installer and accept the defaults.

## 3. Run the setup

1. Open PowerShell **in the agent's folder** ([how](#how-to-type-a-command-you-will-do-this-a-few-times)).
2. Run these two lines, one at a time:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\setup.ps1
   ```

The setup takes a few minutes the first time. It:
- downloads Python and the agent's packages into a `.venv` folder inside the agent's folder
- checks that LibreOffice (or Excel) is installed
- creates the secrets file `.env`
- runs a configuration check

**At the end it will list problems in yellow, marked ✗.** That's expected: you haven't filled in the settings yet (steps 4–8). It never creates or changes anything on the shared drive, and it's safe to run again at any time.

## 4. Get a Claude API key

The API key lets the agent use Claude. Treat it like a password.

1. Go to https://console.anthropic.com and sign in (or create an account, ideally with a VSCP email).
2. **Add credit:** **Settings > Billing**. $20 covers roughly 20–40 weekly reports.
3. **Set a spending limit** (recommended): **Settings > Limits**, for example $50 a month.
4. **Create the key:** **Settings > API keys > Create key**. Name it `VSCP trading agent`.
5. **Copy the key** (it starts with `sk-ant-`). It's shown only once. Keep it open for step 6.

## 5. Prepare the mailbox (Gmail)

Use a mailbox that receives **only** the trading updates, for example a new Gmail account `vscp.trading.updates@gmail.com`. The agent reads new emails in it, and sends its own emails from it. It never deletes, moves or marks emails as read.

1. Sign in to that Gmail account.
2. Turn on **2-Step Verification**: https://myaccount.google.com/security > **2-Step Verification**. Google requires it for the next step.
3. Create an **app password** (a separate password just for the agent): https://myaccount.google.com/apppasswords
   - App name: `VSCP agent`, then **Create**.
   - Google shows a **16-letter password** like `abcd efgh ijkl mnop`. Copy it for step 6. Spaces don't matter.
4. Ask each portfolio company to send its weekly file to this address. If someone at VSCP forwards the files instead, the email comes **from the person forwarding it**, so that person's address must also be on the company's sender list (step 8).

> The agent needs the **app password**, not the normal Gmail password.

Using **Microsoft 365** (an `@vscpllc.com` mailbox) instead needs a one-time setup by VSCP's IT. What they do, and what changes in the agent's settings afterwards, is in [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md), section 3.

## 6. Fill in the secrets file (`.env`)

`.env` holds the passwords. It stays on this PC and is never uploaded or emailed.

In PowerShell in the agent's folder, run:

```powershell
notepad .env
```

Fill in the three lines at the top, directly after the `=` sign, with **no spaces and no quotes**:

| Line | Type after the `=` | Example |
|---|---|---|
| `ANTHROPIC_API_KEY=` | The Claude key from step 4 | `ANTHROPIC_API_KEY=sk-ant-api03-AbC...xyz` |
| `MAIL_USER=` | The mailbox address from step 5 | `MAIL_USER=vscp.trading.updates@gmail.com` |
| `MAIL_APP_PASSWORD=` | The 16-letter app password from step 5 | `MAIL_APP_PASSWORD=abcdefghijklmnop` |

Leave the rest of the file as it is. Save and close.

> Can't find `.env`? It's created by `.\setup.ps1` (step 3). Run that first.

## 7. Fill in the settings file (`config.yaml`)

```powershell
notepad config.yaml
```

Change two things.

**a) Where the shared drive is (`root:`).** This is the **Portfolio** folder that contains one folder per company (`Inceptua`, …).

1. In File Explorer, go to that Portfolio folder (**not** inside a company's folder).
2. Click the address bar, and copy the path (Ctrl+C). It looks like `C:\Users\jsmith\Vesey Street Capital\Portfolio - Documents`.
3. In Notepad, find the line `root: 'CHANGE_ME_path_to_portfolio_folder'`.
4. Replace `CHANGE_ME_path_to_portfolio_folder` with the path, **keeping the `'` marks on both sides**:
   ```yaml
   root: 'C:\Users\jsmith\Vesey Street Capital\Portfolio - Documents'
   ```

The agent expects each company's weekly files in `<Portfolio folder>\<Company>\Trading Updates\<year>`, for example `...\Portfolio - Documents\Inceptua\Trading Updates\2026`. If VSCP's folders are named differently, change the `path_template:` line below it, for example to `"{root}/{company}/Reporting/Weekly/{year}"`. Step 9 shows the folder it will use for each company.

**b) Who gets the emails (`notify:` → `to:`).** Find:

```yaml
notify:
  to:
    - CHANGE_ME_your_email@example.com  # <- CHANGE: ...
```

Replace `CHANGE_ME_your_email@example.com` with your email address. To add more people, add a line for each one, starting with the same spaces and `- `:

```yaml
notify:
  to:
    - jsmith@vscpllc.com
    - analyst@vscpllc.com
```

These people receive **Review needed**, **Approved and saved** and failure emails. The agent never emails the portfolio companies.

Save and close.

## 8. Set up the portfolio companies

Each company has one small file in the **`companies`** folder. It tells the agent the company's folder name, which email addresses it sends from, and its financing terms.

### Inceptua (already prepared)

```powershell
notepad companies\inceptua.yaml
```

Under `senders:`, replace `CHANGE_ME_inceptua_sender@example.com` with the address Inceptua sends its weekly file from. **Only emails from the addresses listed here are processed.** Add one line per address:

```yaml
senders:
  - finance@inceptua.com
  - jsmith@vscpllc.com          # someone at VSCP who forwards Inceptua's file
```

The folder name (`key: Inceptua`) and financing terms are already filled in. Check that `Inceptua` matches the folder name on the shared drive exactly.

### Adding another company

The folder **`company_template`** has a ready-made template, and an example of a finished one.

1. In File Explorer, open the `company_template` folder. **Copy** `NEW_COMPANY_TEMPLATE.yaml` (Ctrl+C).
2. Open the `companies` folder and **paste** it (Ctrl+V).
3. **Rename** the copy to the company's name: lowercase, no spaces, ending in `.yaml`. For example `meridian.yaml`.
   > Windows may hide the `.yaml` ending. If the template shows as just `NEW_COMPANY_TEMPLATE`, type only `meridian`.
4. Open it: `notepad companies\meridian.yaml`. Every line has a note explaining it. Replace each `CHANGE_ME`:

| Setting | What to type | Example |
|---|---|---|
| `key:` | The company's folder name on the shared drive, **spelled exactly** like the folder | `"Meridian Health"` |
| `display_name:` | The full name for emails and the dashboard | `"Meridian Health Group"` |
| `name:` | The short name used inside the company's Excel file (e.g. in "Meridian Holdco") | `"Meridian"` |
| `senders:` | The address(es) the company sends from, one per line | `- finance@meridian-health.com` |
| `model_start_date:` | The date the company's cash model starts, `"YYYY-MM-DD"` in quotes | `"2026-06-01"` |
| `po_advance_rate:` | The lender's advance rate on purchase orders, as a number: 121% is `1.21` | `1.21` |

Keep the quote marks where the template has them. Don't know the financing terms? Ask the deal team.

5. **First week only — the opening loan balance.** Each week's loan balance continues from last week's approved report (`..._vClaude.xlsx`) in the company's folder. If that report **isn't** there when the first week arrives, find the line `# opening_loan_balance_eur: 0.00`, delete the `#` at the start, and type the "Loans - BoP" figure from the last report you trust (no commas): `opening_loan_balance_eur: 4456549.74` (example). After the first week is approved, put the `#` back.

6. Save and close. Then run the check (step 9).

To see what a finished file looks like, open `company_template\EXAMPLE_FILLED_IN.yaml`. Files in `company_template` are never used by the agent; only files in `companies` are.

> A company whose Excel file is laid out differently from Inceptua's is handled automatically: on its first file, Claude works out where each number is, and you approve that "map" together with the first report.

## 9. Check everything

In PowerShell in the agent's folder:

```powershell
.\start.ps1 -Check
```

When everything is right, you see:

```
  ✓ configuration OK
  company Inceptua: pipeline=True senders=1 -> C:\Users\...\Portfolio - Documents\Inceptua\Trading Updates\2026
```

- Check that the folder after `->` is where that company's weekly files really are.
- Each line marked **✗** says what to fix. The most common ones are in [section 12](#12-if-something-goes-wrong).

## 10. Start the agent

```powershell
.\start-all.ps1
```

- Two small windows open (minimised): the **service**, which checks the mailbox every minute, and the **dashboard**.
- Your browser opens the dashboard at **http://localhost:8501** (only this PC can open it). The top bar shows a green **Service running**.
- **Keep both windows open.** Closing them stops the agent.

**To stop:** close the two windows (or press Ctrl+C in them).
**To start it again later:** open PowerShell in the agent's folder and run `Set-ExecutionPolicy -Scope Process Bypass`, then `.\start-all.ps1`.
**To start it automatically whenever you log on to Windows:** run `.\install-autostart.ps1 -Dashboard` once. (Remove it with `.\install-autostart.ps1 -Uninstall`.)

## 11. Every week: reviewing a report

| When | What happens |
|---|---|
| The company emails its file | Within about a minute, the dashboard's top bar shows **Processing Inceptua Group CW38 2026**, and the source file appears in the company's folder on the shared drive |
| About 5 minutes later | You get a **Review needed: Inceptua Group CW38 2026** email with the report attached and a link to the dashboard |
| You open the dashboard's **Review queue** | It shows the week in words, the figures against last week, and every check. Click **Download the output to check it** and open the file in Excel to look through it |
| You type your name and click **Approve and publish** | Within about 10 seconds the report is saved as `Trading_update_CW38_2026_vClaude.xlsx` next to the source file, and everyone gets an **Approved and saved** email |
| Or you click **Reject** with a reason | Nothing is saved. Everyone gets a **Rejected, not saved** email |

**Weeks build on each other.** A week's report needs last week's approved report. If a week arrives before last week is approved, it goes **On hold** (you get an email) and runs by itself once last week is approved.

**Other emails you may get:**
- **ACTION NEEDED: … was not produced**: the report failed a check, even after one automatic retry. The email says why. Nothing was saved to the drive. Usually the source file has a problem; ask the company for a corrected file.
- **ACTION NEEDED: the agent cannot read the inbox**: it failed to reach the mailbox 3 times in a row, e.g. the app password was changed.

**Build a report from a file you already have** (for example, to try it out, or to redo a failed week). It goes to the review queue as usual, and the emails are shown on screen instead of sent:

```powershell
.venv\Scripts\Activate.ps1
python -m agent process "C:\path\to\Trading_update_CW38_2026.xlsx" --company Inceptua --no-email
```

`--company` is the company's `key:` from its file in `companies`.

## 12. If something goes wrong

| What you see | What to do |
|---|---|
| "**running scripts is disabled** on this system" | Run `Set-ExecutionPolicy -Scope Process Bypass` in the same window first |
| "**uv is not installed**" or "uv is not recognized" | Do [step 2](#2-install-two-programs), then **close PowerShell and open a new window** |
| "**No .venv found**" | Run `.\setup.ps1` first (step 3) |
| ✗ **set root in config.yaml** / **root folder does not exist** | Step 7a. The path must be the Portfolio folder as this PC shows it, between `'` marks. Is OneDrive running and synced? |
| ✗ **replace the placeholder addresses** | A `CHANGE_ME` email address is left in `config.yaml` or a file in `companies` (steps 7b, 8) |
| ✗ **fill in the CHANGE_ME values** | A company file copied from the template isn't finished (step 8) |
| ✗ **mail credentials missing** | `MAIL_USER` or `MAIL_APP_PASSWORD` is empty in `.env` (step 6) |
| ✗ **ANTHROPIC_API_KEY is not set** | Step 6 |
| Gmail login fails ("Username and Password not accepted") | Use the 16-letter **app password**, not the Gmail password. 2-Step Verification must be on (step 5) |
| **401** or "authentication" errors from Claude | The API key in `.env` is wrong or was deleted, or the account has no credit (step 4) |
| A yaml error mentioning a **line and column** | A file in `companies` or `config.yaml` has a typing slip: usually missing spaces at the start of a line, or a missing `'`/`"`. Compare with `company_template\EXAMPLE_FILLED_IN.yaml` |
| The email arrives but **nothing happens** | The sender isn't on that company's `senders:` list (forwarded emails come from the person forwarding). The service window says "sender … is not on any allowlist". Also check the file name looks like `Trading_update_CW38_2026.xlsx` |
| "**no opening loan balance**" (first report) | Last week's `_vClaude` report isn't in the company's folder. See step 8, point 5 |
| **"Neither LibreOffice nor Excel found"** | Install LibreOffice (step 2), then run `.\setup.ps1` again |
| A report takes **more than 10 minutes** | The PC is low on memory. Close other programs |
| The dashboard says **Service not running** | The service window was closed or the PC restarted. Run `.\start-all.ps1` again |

**Where the agent keeps its notes:** `data\service.log` (what it did, line by line) and `data\_runs\` (one folder per report, including everything Claude did). Send these to whoever supports the agent.

**Commands for support staff** (run `.venv\Scripts\Activate.ps1` first):

| Command | What it does |
|---|---|
| `python -m agent check` | Same as `.\start.ps1 -Check` |
| `python -m agent poll-once` | Check the mailbox once, process what's new, and stop |
| `python -m agent review list` | Reports waiting for review |
| `python -m agent review approve ID --by NAME` | Approve from the command line (`reject ID --reason TEXT --by NAME` to reject) |
| `.\start.ps1` / `.\start-dashboard.ps1` | Start only the service / only the dashboard |

## 13. What's in this folder

| Folder or file | What it is | Do you edit it? |
|---|---|---|
| `README.md` | This guide | No |
| `.env` | **Your secrets**: Claude key, mailbox password. Created by `setup.ps1`. Never shared or uploaded | **Yes** (step 6) |
| `config.yaml` | Settings: shared drive folder, who gets emails | **Yes** (step 7) |
| `companies\` | One file per portfolio company | **Yes** (step 8) |
| `company_template\` | A blank company file to copy, and a filled-in example. Not used by the agent | Copy from it |
| `docs\` | Further reading (below) | No |
| `setup.ps1`, `start-all.ps1`, `start.ps1`, `start-dashboard.ps1`, `install-autostart.ps1` | The commands you run | No |
| `agent\` | The agent's program: mailbox, Claude, checks, review queue, saving to the drive | No |
| `dashboard\` | The dashboard web page | No |
| `.claude\skills\` | The written instructions Claude follows to build a report, and to map a new company's file layout | No |
| `.env.example`, `pyproject.toml`, `uv.lock`, `.streamlit\`, `.gitignore` | Technical files used by the setup | No |
| `data\` | Created when the agent runs: review queue, logs, history. Stays on this PC, never on the shared drive | No |

**The `docs` folder** holds two documents the README doesn't cover:

| File | For whom | Why it's here |
|---|---|---|
| [`HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) | Anyone at VSCP | Explanation with diagrams: what the agent does, what's finished, its limits, and what VSCP needs to provide to make it a full product |
| [`NEXT_STEPS.md`](docs/NEXT_STEPS.md) | VSCP management and IT | The next stage: running the agent safely on an always-on PC or in the cloud, a secure connection to Microsoft 365 email (and why it was tested on Gmail), a secure connection to the shared drive, what's needed from VSCP, and the questions to answer |

**Why there is no `samples` folder:** the sample workbooks VSCP provided contain a portfolio company's real financial figures. The agent doesn't need them to run (the report layout and look are built into the program), so they are deliberately left out of this download.

---

## Costs, data and safety

- **Cost:** about $0.60–1.20 of Claude usage per weekly report; learning a new company's layout once costs about $1.50. Each run is capped at $5 (`max_budget_usd` in `config.yaml`).
- **What leaves the PC:** each run sends that week's workbook (and last week's, for the comparison) to Anthropic's API. Nothing else on the drive is sent. Check this fits VSCP's data policy.
- **The shared drive is only added to:** the agent saves new files and never overwrites or deletes anything.
- **Claude works on copies** in a sealed folder on this PC. It cannot reach the drive, the mailbox or the internet.
- **To confirm with VSCP:** the Cash Schedule opens bank cash from the company's **total** bank cash, not the single account the sample used. See [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md), section 6.
