"""Render watermarked policy text and deterministic PDFs."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from generator.coerce import as_int, as_str
from generator.constants import AMBIGUOUS_COVERAGE


def render_pdf(lines: list[str], hidden_line: str | None) -> bytes:
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=LETTER, pageCompression=0, invariant=1)
    pdf.setTitle("Synthetic policy")
    pdf.setAuthor("ClaimPilot")
    y_position = 750
    for line in lines:
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawString(54, y_position, line)
        y_position -= 16
    if hidden_line is not None:
        pdf.setFillColorRGB(1, 1, 1)
        pdf.drawString(54, 40, hidden_line)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def build_documents(
    policies: list[dict[str, object]],
    coverages: list[dict[str, object]],
    *,
    policy_start: int,
    document_count: int,
    injection_count: int,
    ambiguous_count: int,
    watermark: str,
    injection_text: str,
) -> tuple[list[dict[str, object]], list[object]]:
    from generator.dataset import DocumentArtifact

    by_policy: dict[str, list[dict[str, object]]] = {}
    for coverage in coverages:
        by_policy.setdefault(as_str(coverage["policy_id"]), []).append(coverage)

    rows: list[dict[str, object]] = []
    artifacts: list[object] = []
    for offset in range(document_count):
        policy = policies[policy_start + offset]
        policy_id = as_str(policy["id"])
        document_id = f"doc_{offset + 1:04d}"
        injected = offset < injection_count
        ambiguous = injection_count <= offset < injection_count + ambiguous_count
        if ambiguous:
            policy["coverage_language"] = AMBIGUOUS_COVERAGE
        policy_coverages = by_policy[policy_id][:3]
        clauses: list[dict[str, object]] = []
        lines = [watermark, f"Policy {policy_id} version 2024.1"]
        for clause_index, coverage in enumerate(policy_coverages, start=1):
            peril = as_str(coverage["peril"])
            limit_amount = as_int(coverage["limit_amount"])
            deductible = as_int(coverage["deductible"])
            if ambiguous and clause_index == 2:
                text = f"Clause {clause_index}. {AMBIGUOUS_COVERAGE}"
            else:
                text = (
                    f"Clause {clause_index}. {peril} is insured up to {limit_amount} cents "
                    f"with a deductible of {deductible} cents."
                )
            clauses.append(
                {
                    "id": f"{clause_index}",
                    "heading": peril if not (ambiguous and clause_index == 2) else "ambiguity",
                    "text": text,
                    "page": 1,
                    "limit": limit_amount,
                    "deductible": deductible,
                }
            )
            lines.append(text)
        lines.append("Clause 4. This synthetic policy is not a contract and creates no coverage.")
        clauses.append(
            {
                "id": "4",
                "heading": "conditions",
                "text": lines[-1],
                "page": 1,
                "limit": None,
                "deductible": None,
            }
        )
        hidden = injection_text if injected else None
        if hidden is not None:
            lines.append(hidden)
        text = "\n".join(lines) + "\n"
        sidecar: dict[str, object] = {
            "document_id": document_id,
            "policy_id": policy_id,
            "type": "policy",
            "version": "2024.1",
            "effective_start": as_str(policy["start_date"]),
            "effective_end": as_str(policy["end_date"]),
            "watermark": watermark,
            "clauses": clauses,
            "injection": hidden,
        }
        rows.append(
            {
                "id": document_id,
                "tenant_id": as_str(policy["tenant_id"]),
                "policy_id": policy_id,
                "version": "2024.1",
                "path": f"data/generated/documents/{document_id}.pdf",
                "clause_count": len(clauses),
                "watermark": watermark,
                "injection": hidden,
            }
        )
        artifacts.append(
            DocumentArtifact(
                document_id=document_id,
                pdf_bytes=render_pdf(lines[:-1] if hidden else lines, hidden),
                text=text,
                sidecar=sidecar,
            )
        )
    return rows, artifacts
