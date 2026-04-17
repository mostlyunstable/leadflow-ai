"""
Email Optimization Engine — Track performance and improve generation over time.
Implements simple A/B tracking and feeds best-performing patterns back to the generator.
"""

import logging
from typing import Optional

from database.database import get_session
from database.models import EmailTemplate, EmailRecord, EmailType, Reply

logger = logging.getLogger(__name__)


def record_template(subject: str, body: str, email_type: EmailType = EmailType.INITIAL):
    """
    Store a sent email as a template for performance tracking.
    Deduplicates by subject pattern.
    """
    with get_session() as session:
        # Check if similar template exists (by subject)
        existing = (
            session.query(EmailTemplate)
            .filter_by(subject_pattern=subject, email_type=email_type)
            .first()
        )

        if existing:
            existing.times_used += 1
        else:
            template = EmailTemplate(
                subject_pattern=subject,
                body_pattern=body,
                email_type=email_type,
                times_used=1,
            )
            session.add(template)


def record_reply(email_record_id: int):
    """
    When a reply is received, increment the reply count for the matching template
    and update its performance score.
    """
    with get_session() as session:
        record = session.query(EmailRecord).get(email_record_id)
        if not record:
            return

        template = (
            session.query(EmailTemplate)
            .filter_by(
                subject_pattern=record.subject,
                email_type=record.email_type,
            )
            .first()
        )

        if template:
            template.reply_count += 1
            # Performance score = reply rate (replies/uses)
            if template.times_used > 0:
                template.performance_score = round(
                    (template.reply_count / template.times_used) * 100, 2
                )
            logger.info(
                f"Template '{template.subject_pattern}' performance updated: "
                f"score={template.performance_score}%"
            )


def get_top_performing_templates(
    limit: int = 3,
    min_uses: int = 2,
    email_type: EmailType = EmailType.INITIAL,
) -> list[dict]:
    """
    Get the best-performing email templates for use as few-shot examples.
    
    Args:
        limit: Maximum number of templates to return
        min_uses: Minimum times used to be considered (avoids noise from small sample)
        email_type: Type of email template to fetch
        
    Returns:
        List of dicts with subject and body keys
    """
    with get_session() as session:
        templates = (
            session.query(EmailTemplate)
            .filter(
                EmailTemplate.email_type == email_type,
                EmailTemplate.times_used >= min_uses,
                EmailTemplate.performance_score > 0,
            )
            .order_by(EmailTemplate.performance_score.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "subject": t.subject_pattern,
                "body": t.body_pattern,
                "score": t.performance_score,
                "uses": t.times_used,
                "replies": t.reply_count,
            }
            for t in templates
        ]


def get_optimization_report() -> dict:
    """
    Generate an optimization report with performance insights.
    
    Returns:
        dict with top performers, overall stats, and recommendations
    """
    with get_session() as session:
        total_templates = session.query(EmailTemplate).count()
        total_uses = sum(
            t.times_used for t in session.query(EmailTemplate).all()
        ) if total_templates > 0 else 0
        total_replies = sum(
            t.reply_count for t in session.query(EmailTemplate).all()
        ) if total_templates > 0 else 0

    top_performers = get_top_performing_templates(limit=5, min_uses=1)

    overall_reply_rate = (
        round((total_replies / total_uses) * 100, 1) if total_uses > 0 else 0
    )

    return {
        "total_templates": total_templates,
        "total_uses": total_uses,
        "total_replies": total_replies,
        "overall_reply_rate": overall_reply_rate,
        "top_performers": top_performers,
        "recommendation": _generate_recommendation(overall_reply_rate, top_performers),
    }


def _generate_recommendation(reply_rate: float, top_performers: list[dict]) -> str:
    """Generate a human-readable optimization recommendation."""
    if not top_performers:
        return "Not enough data yet. Send at least 20 emails to start seeing optimization insights."

    if reply_rate >= 15:
        return "Excellent reply rate! Your emails are performing well above industry average (1-5%)."
    elif reply_rate >= 5:
        return "Good reply rate. Consider testing shorter subject lines and more specific first lines."
    elif reply_rate >= 1:
        return (
            "Average reply rate. Try varying your value proposition and testing "
            "question-based subject lines."
        )
    else:
        return (
            "Low reply rate. Consider: (1) improving lead targeting, "
            "(2) making subject lines more curiosity-driven, "
            "(3) ensuring first lines are truly personalized."
        )
