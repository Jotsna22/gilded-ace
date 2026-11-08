# The Gilded Ace — Devpost write-up (≤400 words)

The Gilded Ace is a Streamlit decision desk for a fictional casino floor. DuckDB reads the parquet tables; every dollar on screen starts there. The question is not which cabinets look worst, but which ones would repay a July dollar.

Jan–Jun 2025, the ten lowest house-win cabinets are not a buy list. Fair tests clear them as location (7), short tenure (2), or payout inspect (1). Zero of those ten are on-pace replacements. All 46 location cases sit in Back Forty. One natural experiment already moved: M-1152 Jackpot Summit did about $119 coin-in per hour in Back Forty and about $245 after it reached Main Entrance.

We fund three catalog actions and leave most of the $100,000 unused. Three Jackpot Summit cabinets move from Back Forty to warm empty slots in Center Pit and Hotel Corridor ($5,400). Wayfinding refreshes Back Forty ($7,500). Four high negative-luck cabinets get paytable inspection ($4,800). Total spend $17,700; $82,300 stays unspent. Planning theo uses half the observed location gap; M-1152’s full gap is the upside. Inspections book $0 theo—they buy information, not a finding of misconduct.

Demand is a weekday-mean forecast of property coin-in, frozen on Jan–Apr and scored on May–Jun only. Weekday MAE is about $69k versus about $218k for a flat training mean. Las Vegas visitation is not a feature. A $15k promo still needs roughly $159k of coin-in to clear theo hold, so promotions are not the July capital plan.

Judges can open the interactive desk, click a period or zone, walk the floor map, and read the Gemini call sheet that narrates the same facts JSON without inventing numbers.

*(~268 words)*
