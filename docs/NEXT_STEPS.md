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

If VSCP uses Microsoft 365 (Outlook) for email. The pilot was tested on a Gmail mailbox instead, for three reasons:

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

