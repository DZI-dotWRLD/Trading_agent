# Next steps: running the agent safely at VSCP

This page is for anyone at VSCP, no technical background needed. The next stage has one goal: **run the agent safely, all the time, connected securely to VSCP's own Microsoft 365 email and shared drive.**

It covers:

1. [Where the project is today](#1-where-the-project-is-today)
2. [Where the agent runs: an always-on PC or the cloud](#2-where-the-agent-runs-an-always-on-pc-or-the-cloud)
3. [A secure connection to Microsoft 365 email](#3-a-secure-connection-to-microsoft-365-email), and why it was tested on Gmail
4. [A secure connection to the shared drive](#4-a-secure-connection-to-the-shared-drive)
5. [What we need from VSCP](#5-what-we-need-from-vscp)
6. [What gets done, and how long it takes](#6-what-gets-done-and-how-long-it-takes)
7. [Questions for VSCP](#7-questions-for-vscp)

For how the agent works, see [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md). For installing it, see the main [`README.md`](../README.md).

---

## 1. Where the project is today

The agent is a **working pilot** that does the full weekly job:
- it picks up a company's emailed trading update
- files it on the shared drive
- has Claude build the report tabs
- checks every number independently
- waits for a person to approve the report before saving it

So far it has run on one ordinary PC, with a Gmail mailbox and a local test folder standing in for the shared drive. Three things are needed before VSCP can rely on it every week:
- **a machine that is always on**
- **VSCP's own Microsoft 365 mailbox**
- **VSCP's real shared drive**

Each must be connected in a way that gives the agent only the access it needs. That's what this page is about.

## 2. Where the agent runs: an always-on PC or the cloud

The agent only works while its machine is switched on and logged in. A laptop that sleeps or goes home misses files. There are two good options, and the agent itself is the same in both.

| | **A. An always-on PC in the office** | **B. A virtual machine in VSCP's cloud (Azure)** |
|---|---|---|
| What it is | A small desktop that stays on, used only for the agent | A Windows computer rented in Microsoft's cloud, reached by remote desktop |
| Setup | The same as in the README | The same as in the README |
| Running cost | Electricity | A monthly Azure fee for a small machine with 8 GB of memory; VSCP's IT can price it |
| Stays on through power cuts, office moves, holidays | No | Yes |
| Backups and health alerts | Set up by hand | Built into Azure |
| Physical security | Depends on where it sits | Microsoft's data centre |
| Best for | A short pilot | Running it for real |

**Recommendation:** start on whichever is ready first, and move to **B** for the long term. Moving is a reinstall, about an hour.

The machine needs **8 GB of memory or more**, and nothing else running on it. Low memory was the only cause of slow runs in testing.

### Making the machine safe (both options)

| Measure | What it protects against |
|---|---|
| **A dedicated Windows account for the agent** (e.g. `svc-trading-agent`), not a person's account | The agent can only do what that account is allowed to do, and nothing depends on one employee's login |
| **The agent's secrets file (`.env`) readable only by that account** and administrators | Someone else on the machine reading the Claude key or the mailbox password |
| **Disk encryption** (BitLocker on a PC; on by default in Azure) | A stolen disk exposing reports or secrets |
| **Automatic Windows updates and antivirus** | Ordinary security holes |
| **No incoming connections from the internet.** The agent only makes outgoing connections, to Microsoft and Anthropic | Anyone reaching the agent from outside |
| **The dashboard stays private.** Reviewers use it through remote desktop, or later behind VSCP's Microsoft sign-in | Anyone on the network approving reports |
| **Automatic restart** at logon, and if the agent stops (`install-autostart.ps1`) | Missed files after a restart |
| **An alert if the agent stops.** If it goes quiet for 30 minutes, the team gets a message. **To be added** (small) | Nobody noticing that reports have stopped |
| **A monthly spending limit** on the Claude account | Unexpected costs |

## 3. A secure connection to Microsoft 365 email

### Why it was tested on Gmail and not Microsoft 365

VSCP uses Microsoft 365 (Outlook) for email. The pilot was tested on Gmail instead, for three reasons:

**1. Connecting to a company's Microsoft 365 needs that company's IT administrator.**
A program can't simply log in to a Microsoft 365 mailbox with a password. An administrator first has to register the program in VSCP's Microsoft account and give it permission to use one mailbox. Only VSCP's IT can do that, and the project had no access to VSCP's systems.

**2. Microsoft has switched off simple password log-in for programs.**
Gmail still lets a program log in with an "app password", which takes five minutes to create. Microsoft 365 has retired that method for security reasons. The proper, more secure route needs IT (point 1).

**3. Gmail let us test everything else for real.**
Every part of the workflow could be tested with real emails, attachments and notifications, at no cost and without waiting for approvals.

**What this means for VSCP:** the mailbox is a separate, replaceable part of the agent. Everything else stays the same with Microsoft 365. The Microsoft 365 connection **has already been written**. It has been tested against a simulation of Microsoft's service, but never against a real Microsoft 365 account, because that needs VSCP's IT. Switching over is a setup task, not a rebuild.

### What VSCP's IT does (about 30–60 minutes)

1. **Create a dedicated mailbox**, for example `trading-updates@vscpllc.com`.
   - A "shared mailbox" is enough, and it needs no paid licence.
   - Portfolio companies send their weekly files to it. Alternatively, an email rule copies them there from an existing inbox.
2. **Register the agent as an app** in VSCP's Microsoft account (Entra ID). This gives the agent its own ID, separate from any person's account.
3. **Give that app permission to read and send mail for that one mailbox only.**
   - It cannot open anyone else's mailbox, files, Teams or calendar.
   - It only reads. It never deletes, moves or marks emails as read.
4. **Send back four details securely** (through a password manager, never by email):
   - the mailbox address
   - the "tenant ID" (VSCP's Microsoft account number)
   - the "client ID" (the agent's ID)
   - the "client secret" (the agent's password)

### What happens on the agent's side (about an hour, including testing)

1. The four details go into the agent's secrets file (`.env`) on the agent's machine, which never leaves it:
   ```
   MAIL_USER=trading-updates@vscpllc.com
   GRAPH_TENANT_ID=...
   GRAPH_CLIENT_ID=...
   GRAPH_CLIENT_SECRET=...
   ```
2. One line in `config.yaml` changes, under `mailbox:`, from `type: imap` to `type: graph`.
3. **Test:**
   - Check the mailbox once, without changing anything.
   - Send one test file from a known sender, and confirm the "Review needed" email arrives from the new mailbox.
   - Confirm the agent **cannot** open any other mailbox.

### Good to know

- **The client secret expires**, typically after 12 months. Someone must renew it before then. If it lapses, the agent emails the team that it can't reach the inbox.
- **To switch the agent off at any time,** IT deletes the client secret or the app registration.
- **Large notification emails.** Microsoft limits the agent's emails to about 4 MB. A bigger report isn't attached; the email points to the dashboard instead. Reports so far have been 1.2–1.8 MB.
- **A stopgap that needs no IT work:** an Outlook rule that forwards the trading-update emails to the Gmail mailbox. This works today, but notifications then come from a Gmail address. Acceptable for a short pilot only.

### For IT: technical summary

- Single-tenant app registration with a client secret (or a certificate).
- `Mail.Read` and `Mail.Send` application permissions, **scoped to the one mailbox**.
  - Preferred: Exchange Online **RBAC for Applications**, with the roles `Application Mail.Read` and `Application Mail.Send` and a management scope for that mailbox. Add no Entra API permission, because an Entra grant is tenant-wide and overrides the scope.
  - The older alternative: Entra admin consent plus an **Application Access Policy** (`RestrictAccess`) on a group containing that mailbox.
- Not requested: `Mail.ReadWrite`, any user mailbox, OneDrive/SharePoint, Teams, directory access.
- Outbound HTTPS only, to `login.microsoftonline.com`, `graph.microsoft.com` and `api.anthropic.com`.
- The agent uses the Microsoft Graph API with client credentials: read-only GET requests on the inbox, and `sendMail`.

## 4. A secure connection to the shared drive

### How the agent uses the drive

The agent sees the shared drive as an ordinary folder on its machine. Usually that's SharePoint synced by OneDrive, or a mapped network drive. Within each company's `Trading Updates\<year>` folder, it does three things:
- **reads** last week's files
- **adds** the new source file when it arrives
- **adds** the approved report

It never changes, renames or deletes anything that is already there.

The agent's own protections, already built:
- **Claude never touches the drive.** It works on copies in a sealed folder on the machine, outside the shared drive.
- **Unapproved reports never go on the drive.** They wait in the review queue on the machine.
- **Every run is checked for tampering.** The agent notes the company's folder before and after each run. Any unexpected change stops the run and alerts the team.

### Making the connection secure

The agent's protections are software. Windows and SharePoint permissions add a second lock that doesn't depend on the agent's own code:

| Step | Who | Why |
|---|---|---|
| **Give the agent's Windows account access only to the trading-update folders**, not the whole drive | IT | If anything goes wrong, the damage is limited to those folders |
| **Allow it to read and add files, but not change or delete them.** On a network drive: "create files" without "modify" or "delete". On SharePoint, where rights are per library: "Contribute" on the reports library only, with version history switched on | IT | Even a fault in the agent couldn't overwrite or remove an existing report |
| **Set the synced folders to "Always keep on this device"** in OneDrive | IT or whoever sets up the machine | Otherwise last week's file may be a cloud-only placeholder when the agent needs it |
| **Confirm the folder structure**, e.g. `Portfolio\<Company>\Trading Updates\<year>` | VSCP | The agent saves files exactly where `config.yaml` says. The setup check prints the folder for each company before anything runs |

**SharePoint in the cloud option (B):** OneDrive sync works on an Azure machine exactly as on a PC. It needs the agent's Windows account to be signed in to OneDrive with a Microsoft 365 account that has access to the library. That usually means a licensed account for the agent.

**Not needed now:** connecting to SharePoint directly over the internet, without a synced folder, isn't built. It only matters for a later, fully cloud-native version without any Windows machine.

## 5. What we need from VSCP

| What | Why |
|---|---|
| **A decision: always-on office PC or Azure VM** (section 2), and the machine itself, 8 GB+ memory | The agent only runs while its machine is on |
| **A dedicated Windows account for the agent** on that machine | Its access is limited to what it needs, independent of any employee |
| **The Microsoft 365 mailbox and app access** (section 3) | Companies send to a VSCP address, and the agent reads only that one mailbox |
| **Access to the trading-update folders**: read and add only (section 4), and OneDrive sync if it's SharePoint | The agent can file reports but can never overwrite or delete anything |
| **VSCP's own Anthropic (Claude) account**, with a monthly spending limit | The pilot uses a personal account; costs and data terms should sit with VSCP |
| **Confirmation that sending the weekly workbooks to Anthropic is acceptable** | Claude builds the report through Anthropic's service, so the company's file is sent there |
| **A contact in IT** | For the setup above, and to renew the mailbox secret every year |

## 6. What gets done, and how long it takes

Once section 5 is in place, about **1–2 weeks** (an estimate):

1. Install the agent on the always-on PC or Azure VM, under the dedicated account.
2. Connect the Microsoft 365 mailbox, and test it on VSCP's real account.
3. Connect the shared drive with read-and-add permissions, and check the folder for each company.
4. **Add the "agent has stopped" alert** (section 2), the only new piece to build.
5. Turn on automatic start and restart.
6. A dry run on recent real files, with nothing published until a person approves.
7. A short hand-over: how to check the agent is running, where the logs are, and how to renew the mailbox secret.

## 7. Questions for VSCP

Short answers are fine, and "don't know yet" is a useful answer too.

**Where it runs**
1. Should the agent run on an always-on PC in the office, or on a virtual machine in Azure? Does VSCP already use Azure?
2. If a PC: is there one that can stay on and logged in at all times, somewhere physically secure?
3. Who in IT will set things up and look after the machine? Who should be told if the agent stops, and how (email, Teams)?
4. Are there VSCP security rules every machine must follow (antivirus, encryption, device management)?

**Email**
5. Can IT create a dedicated mailbox (for example `trading-updates@vscpllc.com`) and the app access in section 3?
6. Should portfolio companies send to the new address directly, or should a rule copy their emails there from an existing inbox?
7. Which addresses should receive the agent's notifications?
8. How should IT hand over the client secret securely, and who renews it every year?

**Shared drive**
9. Where do the trading updates live: SharePoint (synced with OneDrive) or a network drive?
10. What is the exact folder path for each company's weekly files?
11. Can the agent's account be limited to reading and adding files in those folders only?
12. If SharePoint: can the agent's account have a Microsoft 365 licence so OneDrive can sync on the agent's machine?

**Data and access**
13. Is it acceptable to send portfolio companies' weekly workbooks to Anthropic's API? Is an agreement needed first (for example, data not used for training)?
14. Who needs to open the dashboard to review reports, and from where: only on the agent's machine, by remote desktop, or from their own PCs with Microsoft sign-in?
