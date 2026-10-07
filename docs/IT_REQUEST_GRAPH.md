# Request to VSCP IT: mailbox access for the trading-update agent

**From:** Danila Ishchanka · **For:** VSCP IT / Microsoft 365 administrator · **Time needed:** about 30 minutes

## What it is for

The trading-update agent runs on a VSCP Windows machine. It watches one mailbox for portfolio companies' weekly Excel files, builds the updated report, and emails the team when a report is ready for review. A person approves every report before anything is saved to the shared drive.

To read and send that mail in Microsoft 365, the agent needs an **app registration with access to one dedicated mailbox only**.

## What it can and cannot do

| | |
|---|---|
| Mailboxes it can reach | **One**, the dedicated mailbox below. Nothing else, once step 3 is done. |
| Reading | Lists the last 7 days of the inbox and downloads Excel attachments. It never marks mail read, moves it or deletes it. |
| Sending | Sends notifications **from that mailbox** to the VSCP addresses listed in its config. |
| Not requested | `Mail.ReadWrite`, any user's own mailbox, OneDrive/SharePoint, Teams or directory access. |
| Network | It calls `login.microsoftonline.com` and `graph.microsoft.com` (and `api.anthropic.com` for the report build). |

## Please set up

### 1. A dedicated mailbox

A **shared mailbox** (no licence needed), for example `trading-updates@vscpllc.com`. Portfolio companies will send their weekly files here, or a mail-flow rule can copy them here from the current inbox.

### 2. An app registration

Entra admin center > **App registrations** > New registration:
- Name: `VSCP Trading Update Agent`
- Supported account types: **this organisational directory only** (single tenant)
- No redirect URI

Then, under **Certificates & secrets**, create a **client secret** (12 months is fine; we'll ask for a new one before it expires). A certificate also works if your policy prefers one.

### 3. Mail permissions, limited to that mailbox

Choose **one** of these two ways to grant the permissions.

**Option A (recommended): Exchange Online RBAC for Applications.** Do **not** add `Mail.Read` or `Mail.Send` under API permissions in Entra, because an Entra grant applies to every mailbox and would override the limit. Grant them in Exchange Online PowerShell instead:

```powershell
Connect-ExchangeOnline
# The enterprise application's IDs: Entra admin center > Enterprise applications > the app > Overview
New-ServicePrincipal -AppId <Application (client) ID> -ObjectId <Object ID> -DisplayName "VSCP Trading Update Agent"
New-ManagementScope -Name "Trading updates mailbox" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'trading-updates@vscpllc.com'"
New-ManagementRoleAssignment -App <Application (client) ID> -Role "Application Mail.Read" -CustomResourceScope "Trading updates mailbox"
New-ManagementRoleAssignment -App <Application (client) ID> -Role "Application Mail.Send" -CustomResourceScope "Trading updates mailbox"

# Check: should say "InScope: True" for this mailbox, and False for any other
Test-ServicePrincipalAuthorization -Identity <Application (client) ID> -Resource trading-updates@vscpllc.com
```

**Option B: Entra consent with an Application Access Policy** (the older method):
1. Under API permissions, add the Microsoft Graph **application** permissions `Mail.Read` and `Mail.Send`, then **Grant admin consent**.
2. Put the mailbox in a mail-enabled security group, then restrict the app to it:

```powershell
New-ApplicationAccessPolicy -AppId <Application (client) ID> -PolicyScopeGroupId <group email> `
  -AccessRight RestrictAccess -Description "Trading update agent: dedicated mailbox only"
Test-ApplicationAccessPolicy -Identity trading-updates@vscpllc.com -AppId <Application (client) ID>
```

## Please send back

- **Directory (tenant) ID**
- **Application (client) ID**
- **Client secret value.** Send it through a password manager or another secure channel, **not by email**. It is stored only in the service's local `.env` file on the VSCP machine.
- **The mailbox address**

## How we'll test it

1. On the VSCP machine: `python -m agent check`, then `python -m agent poll-once`. This reads the inbox once and changes nothing.
2. A test file sent from an allowlisted address should produce a "ready for review" email from the dedicated mailbox.
3. With Option A, `Test-ServicePrincipalAuthorization` against any **other** mailbox should show it is out of scope.

To switch it off at any time, delete the client secret or the app registration. The agent then stops reading mail and raises its own "inbox unreachable" alert.

## Open point for VSCP (not IT)

The agent sends workbook contents to Anthropic's API (Claude) to build the report. Please confirm this is acceptable for portfolio companies' financial data, or tell us which approval is needed.
