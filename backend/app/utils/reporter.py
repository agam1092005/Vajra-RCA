"""PDF report generator and MinIO archiver.

Compiles incident metadata, timeline, evidence classification, and recommendations
into a PDF document and uploads it to a MinIO storage bucket.
"""
from __future__ import annotations

import io
import time
from minio import Minio
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from ..core.config import settings


def generate_and_upload_report(incident: dict) -> str:
    """Generate PDF for the incident and upload to MinIO. Returns the download link."""
    # 1. Initialize MinIO Client
    try:
        minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False
        )
        # Ensure bucket exists
        bucket_name = "vajra-reports"
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
    except Exception as e:
        print(f"[MinIO] Connection warning: {e}. PDF will be generated but not uploaded.")
        minio_client = None

    # 2. Build PDF Document in Memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    story = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=15
    )
    h2_style = ParagraphStyle(
        'H2Style',
        parent=styles['Heading2'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['BodyText'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155'),
        spaceAfter=8
    )
    meta_style = ParagraphStyle(
        'MetaStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#64748b'),
        spaceAfter=10
    )

    # Document Header
    story.append(Paragraph(f"Vajra RCA — Incident Report", title_style))
    story.append(Paragraph(f"Incident ID: #{incident.get('incident_id')}  |  Severity: {incident.get('severity','HIGH').upper()}  |  Status: {incident.get('status','open').upper()}", meta_style))
    story.append(Paragraph(f"Detected At: {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(incident.get('detected_at', time.time())))}  |  Focal Host: {incident.get('focal_node')}", meta_style))
    story.append(Spacer(1, 10))

    # Summary
    story.append(Paragraph("Incident Summary", h2_style))
    story.append(Paragraph(incident.get("summary", "No summary provided."), body_style))
    story.append(Spacer(1, 10))

    # Hypotheses
    story.append(Paragraph("Ranked Root-Cause Hypotheses", h2_style))
    hyps = incident.get("hypotheses", [])
    if not hyps:
        story.append(Paragraph("No hypotheses generated.", body_style))
    else:
        for idx, h in enumerate(hyps, 1):
            root_cause = h.get("root_cause", "Unknown")
            conf = int(h.get("confidence", 0.0) * 100)
            story.append(Paragraph(f"<b>#{idx} Root Cause:</b> {root_cause} (Confidence: {conf}%)", body_style))
            
            # Recommendations
            recs = h.get("recommendations", [])
            if recs:
                recs_bullets = []
                for r in recs:
                    appr = " (Requires Approval)" if r.get("requires_human_approval") else ""
                    recs_bullets.append([f"• {r.get('action')}{appr}", f"Reason: {r.get('reason')}"])
                
                t = Table(recs_bullets, colWidths=[200, 320])
                t.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
                    ('FONTSIZE', (0,0), (-1,-1), 8),
                    ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#475569')),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ]))
                story.append(t)
            story.append(Spacer(1, 6))

    # Timeline
    story.append(Spacer(1, 10))
    story.append(Paragraph("Chronological Event Timeline", h2_style))
    timeline = incident.get("timeline", [])
    if not timeline:
        story.append(Paragraph("No events in timeline.", body_style))
    else:
        timeline_data = [["Time", "Source", "Type", "Description"]]
        for t in timeline:
            timeline_data.append([
                t.get("time", ""),
                t.get("source", ""),
                t.get("type", "").replace("_", " "),
                t.get("text", "")[:75]
            ])
        t_table = Table(timeline_data, colWidths=[65, 75, 85, 295])
        t_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ]))
        story.append(t_table)

    # Build PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # 3. Upload to MinIO
    object_name = f"incident_{incident.get('incident_id')}_{int(time.time())}.pdf"
    if minio_client:
        try:
            minio_client.put_object(
                bucket_name,
                object_name,
                data=io.BytesIO(pdf_bytes),
                length=len(pdf_bytes),
                content_type="application/pdf"
            )
            # Return URL (MinIO console proxy or direct link)
            return f"http://{settings.minio_endpoint}/{bucket_name}/{object_name}"
        except Exception as e:
            print(f"[MinIO] Upload failed: {e}")
            
    return f"/reports/{object_name} (Failed to upload to object storage)"
