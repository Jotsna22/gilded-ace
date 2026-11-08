# AI-use disclosure

**Project:** The Gilded Ace (TAMU Datathon — Dashboard Royale)

| Tool | What it was used for | What it was *not* used for |
|------|----------------------|----------------------------|
| **Cursor / Composer** (coding agent) | App structure, Streamlit UI, DuckDB queries, floor map, deploy scripts, this submission pack | Inventing dollar figures; those come from DuckDB over the challenge parquet |
| **Google Gemini API** (`google-genai`) | Optional manager “call sheet”: narrates a frozen **facts JSON** built in `gilded/facts.py` | Computing scorecard, forecast, or July budget; Gemini never sees raw parquet |
| **No other LLMs** in the scoring path | — | Forecast and diagnosis are deterministic Python |

**Guardrails in product**
- Money and causes are computed in `gilded/scorecard.py`, `gilded/actions.py`, and `gilded/forecast.py`.
- Gemini receives only the facts object and is instructed to narrate, not invent.
- Unusual payouts are labeled **inspect**, not misconduct.

**Human responsibility**
- Architecture, July action choice, and final claims were reviewed against the DuckDB outputs before submission.
