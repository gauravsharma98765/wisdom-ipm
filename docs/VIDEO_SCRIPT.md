# 5-minute walkthrough: script

*About 650 words at a relaxed pace. Screen cues are in brackets. Read it in your own words; it doesn't need to be word-perfect.*

---

**0:00 – The problem** *[write-up, "The short version"]*
WISDOM is a long-term, high-conviction investor. The brief asked for three things: learn the investor's style from ten years of trades, build a portfolio manager on WISDOM's written principles, and explain how it would run in production. My guiding idea was simple: in finance, every number must be repeatable and every claim traceable. So plain code does the maths and the decisions, and AI only does reading and explaining, with its work checked.

**0:30 – Getting the data right** *[notebook 01, reconciliation table]*
The trade file matches buys and sells in lots. I turned it into 510 actual trades and checked every block against the sheet's own subtotals before calculating anything. I also compared each trade with that day's market price range. About a quarter of the money didn't come from a normal market purchase: pre-IPO allotments, a share placement, buybacks. Those count for profit but not for judging timing.

**1:10 – What the trades say** *[Figure 1, then Figure 8]*
The portfolio made ₹88 crore on ₹69 crore, about 15% a year better than the Nifty on the same cash flows. But 84% of that came from Amber. So WISDOM's edge is choosing businesses, not trading. The scorecard shows a real strength, cutting losers quickly, and some habits to guard against: selling the best stock too early, buying after falls, and a very concentrated book. And the winner, Amber, fits the principles best, while the loser, Zee, is exactly what the avoid list warns about.

**2:00 – The portfolio manager** *[flow diagram in the write-up]*
Every quarter, using only data that was public at the time, the system scores business quality by principle, applies the avoid list, and asks: can this return 25% a year over three years? Then it applies guardrails taken straight from the scorecard: a 40% cap per stock, a one-year minimum hold, don't sell a great business just because it looks pricey, and take care after sharp falls. Every suggestion comes with a written reason.

**2:40 – What the backtest teaches** *[Figure 9, then Figure 11]*
I compared two ways of valuing growth over 2018 to 2026. The system had smaller falls than the index but a lower return, because it often sat in cash and never bought Amber. Amber always traded at 40 to 90 times earnings, above the limits a rules engine would normally allow. When I vary that one limit, returns range from about 7.5% to 16%, unevenly. So the key message for WISDOM is: your principles say you'll pay a premium for great growth businesses, but not how much. That number matters more than any other setting.

**3:30 – Where AI fits** *[notebook 03: evidence table, then explanations]*
AI does two jobs. First, it reads the broker reports and pulls out evidence for each principle, with a page number and an exact quote. Code checks every quote against the page and drops anything it can't find. A verified warning can block a new buy, never force a sale. For example, it blocks buying Welspun despite the broker's BUY, because the case depends on an 80% profit rebound. Second, it explains each decision in plain English, and code checks that every number it uses is in the decision record.

**4:15 – Today's view and production** *[recommendation table, then the Part 3 diagram]*
For the current portfolio it suggests exiting Amber and Zee, holding DBL and trimming Welspun, and every line goes to a person. Amber is the interesting one: one principle says avoid businesses needing outside money, another says back businesses reinvesting for growth. The system's job is to show that conflict, not hide it. In production, trades and holdings never leave WISDOM's private cloud. The AI only sees research, and a named person approves every decision.

**4:50 – Close**
Repeatable numbers, checked evidence, honest testing, and a person making the final call. Next, I'd hold the index when nothing qualifies, and refine the borrowing rule.
