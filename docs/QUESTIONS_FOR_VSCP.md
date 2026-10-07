# Questions for VSCP

Points where we changed or had to interpret the provided sample, to confirm at the review on 7 October 2026.

## Q1. Opening bank cash in the Cash Schedule: one account, or total bank cash?

**What the sample does.** In `Trading_update_cw36_2026_vClaude.xlsx`, sheet `Cash Schedule`, row `Bank Cash - BoP`, the catch-up column is `=Cash!$I$28`. In the source file, `Cash!I28` is **one account: Inceptua NL, Citi Bank (EU), EUR 108,990**.

**What we changed.** We open from **`Cash!I29`, "Total Cash at Operating Companies", EUR 18,519,608**, found by its label. It equals the balance sheet's Cash (`Customer-Level!E103`, EUR 18,519.6k), so it reconciles. With I28, every projected bank-cash balance, total cash and Cash Schedule net debt is about EUR 18.4M lower than with the total.
**How we found it.** When Claude mapped a new company's workbook with no hint (ADR-0024), it chose the total, and noted that the single-account value "is only the NL Citi account, not the total".

**To confirm:**
1. Was `I28` a slip (it sits one row above the total), or does the schedule deliberately track one entity's account, for example the vehicle that finances the purchase orders?
2. **Opening date.** The schedule's first column adds every flow since the model start date (1 June 2026), and the loan balance opens at that date. Should bank cash also open at **1 June**, not at the weekly snapshot (2 September in CW36)? Opening at the snapshot and then adding June to September flows counts those months twice. The 1 June balance isn't in the weekly file, so it would be a configured value, like the opening loan balance.
3. Should restricted cash, or the Pharma Model / Holdco cash (Cash incl. Pharma Model, EUR 21.7M vs Cash, EUR 18.5M), be included?

**If VSCP confirms I28 was intended,** it's a one-line change in the source map (`agent/workbook/source_map.py`, `INCEPTUA_MAP["opening_bank_cash"]`), and the validator follows automatically.
