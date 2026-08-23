"""Dependency-free, self-contained evidence report."""

from __future__ import annotations

import json
from collections.abc import Mapping
from html import escape
from pathlib import Path

from .alignment import Alignment
from .domain import EvidenceBundle, Finding, ReviewDecision, to_dict


def write_html(
    bundle: EvidenceBundle, alignments: tuple[Alignment, ...], destination: Path
) -> None:
    data = json.dumps(
        {"bundle": to_dict(bundle), "alignments": to_dict(alignments)}, ensure_ascii=False
    ).replace("</", "<\\/")
    latest_reviews: dict[str, ReviewDecision] = {}
    for review in bundle.reviews:
        latest_reviews[review.finding_id] = review
    semantic_records = bundle.metadata.get("semantic_evaluations", ())
    semantic_counts = {"equivalent": 0, "drift": 0, "abstained": 0}
    if isinstance(semantic_records, (list, tuple)):
        for record in semantic_records:
            if isinstance(record, Mapping) and record.get("outcome") in semantic_counts:
                semantic_counts[str(record["outcome"])] += 1
    semantic_summary = (
        f"<p><b>Semantic evaluations:</b> {sum(semantic_counts.values())} total · "
        f"{semantic_counts['equivalent']} equivalent · {semantic_counts['drift']} drift · "
        f"{semantic_counts['abstained']} abstained. Passing checks remain in the sealed evidence.</p>"
    )

    def review_markup(finding: Finding) -> str:
        if finding.id in latest_reviews:
            review = latest_reviews[finding.id]
            return (
                f"<p><b>Human decision:</b> {escape(review.decision.value)} — "
                f"{escape(review.rationale)}</p>"
            )
        safe_id = escape(finding.id)
        return (
            f'<p><button data-finding="{safe_id}" data-decision="confirmed">Confirm</button>'
            f'<button data-finding="{safe_id}" data-decision="partially_correct">Partially correct</button>'
            f'<button data-finding="{safe_id}" data-decision="rejected">Reject</button>'
            f'<button data-finding="{safe_id}" data-decision="cannot_determine">Cannot determine</button>'
            f'<button data-finding="{safe_id}" data-decision="intentional_localization">'
            "Intentional localization</button></p>"
        )

    rows = (
        "".join(
            f'<article class="finding" data-severity="{escape(f.severity.value)}">'
            f"<h3>{escape(f.title)}</h3><p>{escape(f.explanation)}</p>"
            f"<p><b>{escape(f.severity.value.upper())}</b> · uncalibrated decision score {f.confidence:.2f}</p>"
            + review_markup(f)
            + f"<details><summary>Evidence ({len(f.evidence)})</summary>"
            + "".join(
                f"<pre>{escape(e.block_id)}\n{escape(e.excerpt or 'Evidence absent')}</pre>"
                for e in f.evidence
            )
            + "</details></article>"
            for f in bundle.findings
        )
        or "<p>No findings.</p>"
    )
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>EII evidence report</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:auto;padding:2rem;color:#17202a}}
.finding{{border-left:.4rem solid #e67e22;padding:1rem;margin:1rem 0;background:#f8f9f9}}
.finding[data-severity=high],.finding[data-severity=critical]{{border-color:#c0392b}}
pre{{white-space:pre-wrap;background:white;padding:.7rem}}button{{margin:.25rem}}</style>
<h1>EII Open Learning Observatory</h1><p>Bundle <code>{escape(bundle.id)}</code></p>
<p>{len(bundle.course_releases)} language releases · {len(alignments)} aligned concept groups · {len(bundle.findings)} review hypotheses</p>
{semantic_summary}
<nav><button data-filter="all">All</button><button data-filter="high">High</button>
<button data-filter="medium">Medium</button></nav><main>{rows}</main>
<script type="application/json" id="eii-data">{data}</script>
<script>function filter(s){{document.querySelectorAll('.finding').forEach(x=>x.hidden=s!='all'&&x.dataset.severity!=s)}}
function review(id,decision){{const reviewer=prompt('Reviewer pseudonym');if(!reviewer)return;
const rationale=prompt('Rationale (required)');if(!rationale)return;
const evidence_quality=prompt('Evidence: sufficient, incomplete, wrong, or absent');
const usefulness=Number(prompt('Editorial usefulness from 1 to 5'));
const actionability=prompt('Action: usable, needs_revision, or unusable');
const record={{finding_id:id,decision,reviewer,rationale,created_at:new Date().toISOString(),
evidence_quality,usefulness:Number.isInteger(usefulness)?usefulness:null,actionability}};
const blob=new Blob([JSON.stringify(record)+'\\n'],
{{type:'application/jsonl'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);
a.download='review-'+id+'.jsonl';a.click();URL.revokeObjectURL(a.href);}}
document.querySelectorAll('[data-filter]').forEach(x=>x.addEventListener('click',()=>filter(x.dataset.filter)));
document.querySelectorAll('[data-decision]').forEach(x=>x.addEventListener('click',()=>review(x.dataset.finding,x.dataset.decision)));
</script>
</html>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, "utf-8")
