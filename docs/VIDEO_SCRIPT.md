# Walkthrough video: narration script

The narration of the ~5-minute walkthrough video, one section per slide of the deck. The video was produced as a narrated slideshow (open-source Kokoro-82M text-to-speech), so this is exactly what is spoken.

**01 · Cover**

This is a walkthrough of the WISDOM Intelligent Portfolio Manager. The brief asked for three things: learn the investor's style from ten years of trades, build a portfolio manager on WISDOM's principles, and explain how it would run in production. The guiding idea: plain code does the maths and the decisions, and AI only reads and explains, with its work checked.

**02 · Executive summary**

Here is the summary in five points. First, WISDOM's edge is stock selection, not trading. Second, the investor is disciplined about losses, but impatient with winners. Third, WISDOM's own principles point the right way. Fourth, the system is rules first, and the AI layer is checked. And fifth, one setting matters more than any other: how much premium WISDOM is willing to pay for structural growth.

**03 · Data integrity**

First, the data. The trade file matches buys and sells in lots. I turned it into five hundred and ten actual trades, and every block ties to the sheet's own subtotals. Each trade was also compared with that day's market price range. About a quarter of the money did not come from a normal market purchase: pre-IPO allotments, a share placement, and buybacks. Those count for profit, but not for judging timing.

**04 · Performance**

The portfolio made eighty-eight crore rupees on sixty-nine crore invested. That is a twenty seven and a half percent annual return, and about fifteen percent a year better than the Nifty fifty on the same cash flows. But eighty-four percent of the profit came from one stock, Amber. Zee is the only stock that lagged the index.

**05 · Concentration**

The portfolio was very concentrated. On average it behaved like a portfolio of fewer than two equal-sized stocks, and at its peak Amber was eighty percent of it. That is consistent with high conviction, but it is also the biggest single risk.

**06 · Timing**

On timing, the picture is mixed. Amber was bought well, but sold too early, and the stock kept rising after the sales. DBL and Welspun were the reverse: weak buys, but very well-timed sells. The investor also likes to buy after a fall. About seventy percent of all buying happened after the stock had dropped over six months.

**07 · Scorecard**

The scorecard brings this together. The real strengths are returns against the index, and cutting losses quickly. The weaknesses are sell timing, buying after falls, and concentration. And notice this. The winner, Amber, fits WISDOM's principles best, while the loser, Zee, is exactly what the avoid list warns about. So the weaknesses become guardrails in the system.

**08 · How the system decides**

Here is how the portfolio manager decides. Every quarter, using only data that was public at the time, it scores business quality by principle, applies the avoid list, and asks one question: can this stock return twenty-five percent a year over three years? Then it applies guardrails taken straight from the scorecard. No more than forty percent in one stock, and a one-year minimum hold. Every suggestion comes with a written reason, and a person approves it.

**09 · Backtest**

I tested two ways of valuing growth, over twenty eighteen to twenty twenty-six. The system had smaller falls than the index, but a lower return. It was often in cash, because few stocks passed every test at once, and it never bought Amber.

**10 · Sensitivity to the valuation limit**

Why not Amber? It always traded at forty to ninety times earnings, above the limit a rules engine would normally allow. When I vary that one limit, returns range from about seven and a half to sixteen percent a year, and not in a straight line. So the key message for WISDOM is this. Your principles say you will pay a premium for great growth businesses, but not how much. That one number matters more than any other setting.

**11 · AI layer**

AI does two jobs. First, it reads the broker reports and pulls out evidence for each principle, with a page number and an exact quote. Code checks every quote against the page and drops anything it cannot find. A verified warning can block a new buy, but never force a sale. For example, it blocks buying Welspun despite the broker's buy rating. Second, it explains each decision in plain English, and code checks every number it uses.

**12 · Current portfolio**

For the current portfolio, the system suggests exiting Amber and Zee, holding DBL, and trimming Welspun. Every line goes to a person. Amber is the interesting one. One principle says avoid businesses that need outside money. Another says back businesses that reinvest for growth. The system's job is to show that conflict clearly, not to hide it.

**13 · Production**

In production, data loads run daily and stop if the totals do not match. Financials are stored by the date they became public, so nothing can see the future. WISDOM's trades and holdings never leave its private cloud; the AI only sees research text. And a named person approves every decision.

**14 · Next steps**

To sum up: repeatable numbers, checked evidence, honest testing, and a person making the final call. Next, I would hold the index when nothing qualifies, and separate borrowing to grow from borrowing to survive. Thank you.
