# Claims & Evidence appendix

Slice unless noted: **2025-01-01 → 2025-06-30**, whole floor. Code: `gilded/scorecard.py`, `gilded/actions.py`, `gilded/forecast.py`, `gilded/warehouse.py`.

---

### Claim 1 — The bottom-10 house-win list is not a replacement list
| | |
|--|--|
| **Evidence** | `naive_bottom(scored, 10)` causes: location **7**, short_tenure **2**, payout_inspect **1**, on_pace **0**. Metric “Bottom 10 we would replace” = count of `on_pace` in that list → **0 of 10**. |
| **Table / query** | `prepared_daily_view` + calendar + game_math → scorecard; sort by `house_win` ascending. |
| **Result** | Lowest earners are explained by cold location, short sample, or extreme residual—not “fine machine, wrong unit.” |
| **Alternative** | Rank by theo or coin-in/hour instead of house win; still dominated by Back Forty location cases. |
| **Limitation** | Cause labels are heuristic thresholds (tenure days, luck z, peer cph ratio), not a causal RCT. |

---

### Claim 2 — Location underperformance concentrates in Back Forty
| | |
|--|--|
| **Evidence** | **46 / 46** `cause == location` cabinets have `zone_name == Back Forty`. |
| **Table / query** | Theme×zone coin-in per available hour; machine cph vs same theme elsewhere (`peer_cph_elsewhere`). |
| **Result** | Cold-spot diagnosis is a room problem, not one theme. |
| **Alternative** | Bank-level effects or theme mix inside Back Forty could share blame; we still treat the zone as the actionable unit. |
| **Limitation** | Peer gap uses other zones of the same theme; thin themes make peers noisy. |

---

### Claim 3 — Moving off Back Forty can lift coin-in (natural experiment)
| | |
|--|--|
| **Evidence** | Placement spells for **M-1152** (Jackpot Summit): Back Forty ≈ **$118.8**/hour (34 days) → Main Entrance ≈ **$244.6**/hour (147 days). |
| **Table / query** | `placements` / spell aggregation in `warehouse.placement_spells`. |
| **Result** | Same cabinet, different floor → large cph change; supports relocating cold Jackpot Summit units. |
| **Alternative** | Calendar or demand shift during the spell could confound; other movers (e.g. M-1126) show smaller or opposite moves. |
| **Limitation** | One strong example; July plan still haircuts the gap by **50%** for planning theo. |

---

### Claim 4 — July should spend little of the $100k
| | |
|--|--|
| **Evidence** | Catalog actions: 3× move **$5,400**, 1× wayfinding **$7,500**, 4× inspect **$4,800** → **$17,700** spent, **$82,300** unspent. Move cap follows warm **empty** slots and catalog quantity limits. |
| **Table / query** | `action_catalog`, empty slots on end date, location-case candidates sorted by theo gap. |
| **Result** | Capital stays dry because replacements are not justified; ops moves and signs are cheaper tests. |
| **Alternative** | Aggressive full-gap or more moves if more empty warm slots exist; data caps moves at 3. |
| **Limitation** | Expected July theo is a planning case (half gap for moves/signs); not a guarantee. |

---

### Claim 5 — Weekday-mean forecast beats a flat mean on a time holdout
| | |
|--|--|
| **Evidence** | Train through **2025-04-30**; test **2025-05-01** onward. Weekday MAE ≈ **$68,699**; flat training-mean MAE ≈ **$218,258**. |
| **Table / query** | `property_day` daily coin-in; mean by `local_weekday` vs single train mean. |
| **Result** | Simple seasonality is enough to beat naïve; informs “don’t burn July on a promo by default.” |
| **Alternative** | Add promotions/events or external tourism; we deliberately omit Vegas visitation as a feature. |
| **Limitation** | Short test window; MAE is level error on coin-in, not a betting model. |

---

### Claim 6 — Inspections are information buys, not theo booked
| | |
|--|--|
| **Evidence** | Four inspect targets (e.g. M-1070, M-1290, M-1158, M-1210) with large negative luck z; **expected_july_theo_usd = 0**. |
| **Table / query** | Variance-scaled luck residual vs theo; catalog `A-INSPECT`. |
| **Result** | Extreme residuals can be volatility; we do not treat them as proof of wrongdoing. |
| **Alternative** | Reclassify as luck and skip spend; we still price four inspections because the residual is large enough to check config. |
| **Limitation** | Inspection does not itself raise theo; value is operational clarity. |
