# Next steps and questions for VSCP

This page is for anyone at VSCP, no technical background needed. It explains:

1. [Where the project is today](#1-where-the-project-is-today)
2. [Why it was tested on Gmail and not Microsoft 365](#2-why-it-was-tested-on-gmail-and-not-microsoft-365)
3. [What is needed to switch to Microsoft 365](#3-what-is-needed-to-switch-to-microsoft-365)
4. [What the project needs from VSCP to move forward, and why](#4-what-the-project-needs-from-vscp-to-move-forward-and-why)
5. [Questions for VSCP](#5-questions-for-vscp): what we need to know to continue building, and how VSCP sees the agent

For how the agent works, see [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md). For installing it, see the main [`README.md`](../README.md).

---

## 1. Where the project is today

The agent is a **working pilot**. It runs on one Windows PC and does the full weekly job:
- it picks up a company's emailed trading update
- files it on the shared drive
- has Claude build the four report tabs
- checks every number independently
- waits for a person to approve the report before saving it

It has been tested with real Claude runs and real emails, on Inceptua's files and on test companies whose Excel files are laid out differently.

It has **not yet** run against VSCP's own mailbox, shared drive or real portfolio data beyond the sample. That is the next stage, and it needs VSCP's input. The rest of this page explains what that input is.

## 2. Why it was tested on Gmail and not Microsoft 365

VSCP uses Microsoft 365 (Outlook) for email. The pilot was tested on a Gmail mailbox instead, for three reasons:

**1. Connecting to a company's Microsoft 365 needs that company's IT administrator.**
A program can't simply log in to a Microsoft 365 mailbox with a password. An administrator first has to register the program in VSCP's Microsoft account and give it permission to use one mailbox. Only VSCP's IT can do that, and the project had no access to VSCP's systems during the assignment.

**2. Microsoft has switched off simple password log-in for programs.**
Gmail still lets a program log in with a special "app password", which takes five minutes to create. Microsoft 365 has retired that method for security reasons. So the quick route used for Gmail doesn't work there; the proper, more secure route needs IT (point 1).

**3. Gmail let us test everything else for real.**
With Gmail, every part of the workflow could be tested with real emails, real attachments and real notifications, at no cost and without waiting for anyone's approval.

**What this means for VSCP:** the mailbox is a separate, replaceable part of the agent. Everything else stays the same with Microsoft 365: recognising companies, Claude's build, the checks, the review, the approval and the filing. A Microsoft 365 connection **has already been written**. It has been tested against a simulation of Microsoft's service, but never against a real Microsoft 365 account, because that needs VSCP's IT. Switching over is a setup task, not a rebuild.

## 3. What is needed to switch to Microsoft 365

### What VSCP's IT does (about 30–60 minutes)

1. **Create a dedicated mailbox**, for example `trading-updates@vscpllc.com`.
   - A "shared mailbox" is enough, and it needs no paid licence.
   - Portfolio companies send their weekly files to it. Alternatively, an email rule copies them there from an existing inbox.
2. **Register the agent as an app** in VSCP's Microsoft account (Entra ID). Think of this as giving the agent its own ID card, separate from any person's account.
3. **Give that app permission to read and send mail for that one mailbox only.**
   - It should not be able to open anyone else's mailbox, files, Teams or calendar.
   - It only reads. It never deletes, moves or marks emails as read.
4. **Send back four details securely** (through a password manager, not by email):
   - the mailbox address
   - the "tenant ID" (VSCP's Microsoft account number)
   - the "client ID" (the agent's ID)
   - the "client secret" (the agent's password)

### What happens on the agent's side (about an hour, including testing)

1. The four details go into the agent's private settings file (`.env`) on the VSCP PC, which never leaves that PC:
   ```
   MAIL_USER=trading-updates@vscpllc.com
   GRAPH_TENANT_ID=...
   GRAPH_CLIENT_ID=...
   GRAPH_CLIENT_SECRET=...
   ```
2. One line in `config.yaml` changes, under `mailbox:`, from `type: imap` to `type: graph`.
3. **Test:** check the mailbox once without changing anything, then send one test file from a known sender and confirm the "Review needed" email arrives from the new mailbox.

### Good to know

- **The client secret expires**, typically after 12 months. Someone must renew it before then, or the agent stops reading mail. It warns the team by email when it can't reach the inbox.
- **Large notification emails.** Microsoft limits the emails the agent sends to about 4 MB. A report bigger than that isn't attached; the email points to the dashboard instead. Reports so far have been 1.2–1.8 MB.
- **To switch the agent off at any time,** IT deletes the client secret or the app registration.
- **A stopgap that needs no IT work:** an Outlook rule that forwards the trading-update emails to the Gmail mailbox. This works today, but notifications then come from a Gmail address. Fine for a short pilot, not for the long term.

### For IT: the technical summary

- Single-tenant app registration with a client secret (or a certificate).
- Permissions: `Mail.Read` and `Mail.Send` (application permissions), **scoped to the one mailbox**.
  - Preferred: Exchange Online **RBAC for Applications**, with the roles `Application Mail.Read` and `Application Mail.Send` and a management scope for that mailbox. Add no Entra API permission, because an Entra grant is tenant-wide and overrides the scope.
  - The older alternative: Entra admin consent plus an **Application Access Policy** (`RestrictAccess`) on a group containing that mailbox.
- Not requested: `Mail.ReadWrite`, any user mailbox, OneDrive/SharePoint, Teams, directory access.
- Outbound HTTPS to `login.microsoftonline.com`, `graph.microsoft.com` and `api.anthropic.com`.
- The agent uses the Microsoft Graph API with client credentials, read-only GET requests on the inbox, and `sendMail`.

## 4. What the project needs from VSCP to move forward, and why

| What we need | Why |
|---|---|
| **The Microsoft 365 mailbox and app access** (section 3) | So companies send to a VSCP address and the agent runs inside VSCP's own email system, not a Gmail account |
| **An always-on Windows PC or cloud machine** (8 GB+ memory) with the shared drive synced | The agent only works while its PC is on. A laptop that sleeps or goes home misses files |
| **A dedicated Windows account for the agent**, allowed to add files to the report folders but not to change or delete anything | A second lock, enforced by Windows, on top of the agent's own rule that it never overwrites anything |
| **The list of portfolio companies**: folder names, sender addresses, financing terms, and one recent file each | Each company needs one settings file before its emails are accepted. A recent file lets us confirm the agent reads that company's layout correctly before go-live |
| **The opening loan balance** for each company's first week, if no earlier report is on the drive | Each week's loan balance continues from last week's report. The very first week has nothing to continue from |
| **VSCP's own Anthropic (Claude) account**, with a monthly spending limit | The pilot uses a personal account. Costs and data terms should sit with VSCP. About $0.40–1.00 per report |
| **Approval to send the weekly workbooks to Anthropic** | Each report is built by Claude through Anthropic's service, so the company's file is sent there. VSCP should confirm this fits its data policy and its agreements with portfolio companies |
| **Answers to the questions below** | They decide what is built next, and some change the numbers in the report |

Once these are in place, going live takes about **1–2 weeks** (an estimate): connect the mailbox, move to the always-on machine, set up and check every company, add an alert if the agent stops, and do a dry run on last month's files. The later phases are in [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md), section 8.

## 5. Questions for VSCP

Answers to these decide how the agent is finished. Short answers are fine, and "don't know yet" is a useful answer too.

### A. How VSCP sees the agent

1. What would make this agent a success for VSCP in six months? Time saved, fewer errors, faster reporting to the investment committee, something else?
2. Who should use it day to day: one analyst, the whole deal team, partners?
3. Should it stay focused on weekly trading updates, or grow to other recurring reports (monthly management accounts, covenant compliance, board packs)? Which would be next?
4. Is a person approving every report the right level of control for good, or would VSCP later accept automatic filing when every check passes?
5. How does VSCP feel about AI building reports that feed investment decisions? Is any internal approval or policy needed first?

### B. The current process

6. Who does this work today, and roughly how long does it take per company per week?
7. What happens to the finished report: who reads it, and is it forwarded anywhere (IC, lenders, the company)?
8. Do companies always send on time, in the same format? How often do they resend corrected files?
9. Does anything in today's process not appear in the sample, such as manual adjustments, comments, or calls with the company?

### C. The numbers

10. **Opening bank cash.** In the sample, the Cash Schedule's opening bank cash is `Cash!I28`, which is **one bank account** (Inceptua NL, Citi Bank, about EUR 109k). The agent uses `Cash!I29`, **total cash at operating companies** (about EUR 18.5M), which matches the balance sheet. Which is right? Was I28 a slip, or does the schedule deliberately track one entity's account?
11. **Opening date.** The schedule adds every cash flow since the model start date (1 June 2026), but opens bank cash at the weekly snapshot date. That may count June–September twice. Should bank cash open at 1 June instead?
12. Should restricted cash, or Holdco / "Pharma Model" cash, be included in the cash figures?
13. Are the financing terms (model start date, PO advance rate) the same for every company, or does each have its own? Where are they recorded today?
14. Should every company's report look the same (one VSCP house style), or should each keep its own look?

### D. Portfolio companies

15. How many companies should the agent handle, and which first?
16. Do all of them send the same trading-update template, or do some send something quite different?
17. Who at each company sends the file, and from which addresses? Does anyone at VSCP forward files on their behalf?
18. Should the agent ever reply to the companies (for example "received" or "please resend"), or only email VSCP staff? Today it only emails VSCP.

### E. Review and approval

19. Who may approve reports? Should approval be limited by company, so some people only see their own companies?
20. Should the approval record the person's Microsoft sign-in rather than a typed name?
21. If a report fails its checks, who should be told, and how quickly must it be fixed?
22. Does VSCP want an alert when a company has **not** sent its file by a deadline (for example Monday noon)?

### F. IT, security and data

23. Can IT set up the mailbox and app access in section 3? Who is the contact?
24. Where should the agent run: a PC in the office, a server, or VSCP's cloud (Azure)? Is there a machine that stays on all the time?
25. Where does the shared drive live: SharePoint/OneDrive, or a network drive? What is the exact folder structure for trading updates?
26. Does VSCP have a policy on sending company financial data to an AI provider? Is an agreement with Anthropic (data not used for training, data region) needed?
27. Should notifications also go to Microsoft Teams, or is email enough?
28. Who looks after the agent once it's live: IT, an analyst, or an outside developer?

### G. Dashboard

29. Should the dashboard be reachable from everyone's own PC (with Microsoft sign-in), or is one PC enough?
30. Which figures matter most on the portfolio overview? Is anything missing, or not needed?
31. Should the dashboard data feed other tools, such as Excel, Power BI or a weekly summary email?

### H. Budget and timing

32. Is there a target date for go-live?
33. Is there a monthly budget for running costs (Claude usage, and a cloud machine if chosen)?
34. Who decides on the next phase, and what would they need to see first: a live trial on one company, a comparison with the analysts' own reports, a cost estimate?
