"""One-click visit summary (optional feature c): a printable HTML page in the patient's language with the risk, the
reasons, the what-if choices discussed, the red flags of the last check-in, the next kidney test and the disclaimer.
Built only from the role-filtered record the services layer returned, so it shows nothing the viewer may not see."""
from __future__ import annotations

import html
from datetime import date

from components.theme import LEVEL_COLOR, LEVEL_INK, level_icon
from vrikka.i18n import LANGUAGES, t


def visit_summary_html(rec: dict, lang: str, whatif_rows: list[dict] | None = None) -> str:
    e = html.escape
    lv = rec.get("level", "green")
    risk = (rec.get("risk_text") or "").replace("95% interval", t("risk.interval", lang))
    reasons = "".join(f"<li>{e(t(k, lang))}</li>" for k in rec.get("reasons", [])[:3]) or \
        f"<li>{e(t('summary.none', lang))}</li>"
    wi = ""
    for r in whatif_rows or []:
        if r.get("skipped") or r.get("risk") is None:
            continue
        label = t("lever.continue", lang) if r["name"] == "continue" else t(r["label_key"], lang)
        txt = (r.get("text") or "").replace("95% interval", t("risk.interval", lang))
        wi += f"<tr><td>{e(label)}</td><td class='num'>{e(txt)}</td></tr>"
    wi = f"<table>{wi}</table>" if wi else f"<p>{e(t('summary.none', lang))}</p>"
    last = (rec.get("checkins") or [None])[0]
    flags = e(t("summary.none", lang)) if not last or last["red_flag"] == "none" else \
        f"{e(last['red_flag'])} ({e(last['ts'][:16])})"
    ordered = next((tk for tk in rec.get("tasks", []) if tk["status"] == "ordered"), None)
    if ordered:
        nxt = t("summary.next_test_ordered", lang, date=ordered["ordered_at"][:10])
    elif lv in ("red", "purple"):
        nxt = t(f"action.{lv}", lang)
    else:
        nxt = t("summary.next_test_routine", lang)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(t('summary.title', lang))}</title>
<style>
body {{font-family: "Noto Sans", "Segoe UI", Arial, sans-serif; color:#0b0b0b; background:#fff; max-width:760px;
      margin:24px auto; padding:0 16px; line-height:1.45}}
h1 {{font-size:1.5rem; margin-bottom:0}} h2 {{font-size:1.05rem; margin:18px 0 6px; color:#52514e}}
.badge {{display:inline-block; padding:3px 12px; border-radius:12px; font-weight:700;
        background:{LEVEL_COLOR.get(lv, '#8a8984')}; color:{LEVEL_INK.get(lv, '#fff')}}}
.big {{font-size:1.6rem; font-weight:700}} table {{border-collapse:collapse; width:100%}}
td {{border-bottom:1px solid #e6e5e0; padding:6px 4px}} td.num {{text-align:right; white-space:nowrap}}
.disc {{margin-top:24px; padding:10px; border:1px solid #c3c2b7; font-size:.85rem; color:#52514e}}
button {{margin-top:12px}} @media print {{button {{display:none}}}}
</style></head><body>
<h1>{e(t('summary.title', lang))}: {e(rec.get('name', rec.get('patient_id', '')))}</h1>
<p>{e(t('ui.fictional', lang))} · {date.today().isoformat()} · {e(LANGUAGES.get(lang, lang))}</p>
<h2>{e(t('summary.risk', lang))}</h2>
<p><span class="badge">{level_icon(lv)} {e(t(f'level.{lv}', lang))}</span> <span class="big">{e(risk)}</span></p>
<p><b>{e(t('ui.what_to_do', lang))}:</b> {e(t(f'action.{lv}', lang))}</p>
<h2>{e(t('summary.reasons', lang))}</h2><ul>{reasons}</ul>
<h2>{e(t('summary.whatif', lang))}</h2>{wi}
<h2>{e(t('summary.redflags', lang))}</h2><p>{flags}</p>
<h2>{e(t('summary.next_test', lang))}</h2><p>{e(nxt)}</p>
<div class="disc">{e(t('summary.disclaimer', lang))}</div>
<button onclick="window.print()">{e(t('summary.print', lang))}</button>
</body></html>"""
