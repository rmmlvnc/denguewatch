"""Shared in-app and email notifications for CHO workflow events."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)


def notify_cho_admins(*, title, message, link, actor=None, notification_type='ADMIN', email=True):
    """Notify approved CHO accounts; email only accounts that verified ownership."""
    from .models import UserAccount, notify_user

    recipients = UserAccount.objects.filter(role='CHO', account_status='APPROVED').order_by('pk')
    sender_name = (actor.get_full_name() or actor.username) if actor else 'DengueWatch'
    email_sent = 0
    email_failed = 0
    for recipient in recipients.iterator():
        if actor and recipient.pk == actor.pk:
            continue
        notify_user(
            recipient,
            notification_type,
            title,
            message,
            created_by=actor,
            link=link,
        )
        if not email or not recipient.email_verified or not recipient.email or not settings.EMAIL_DELIVERY_ENABLED:
            continue
        text_body = f'{title}\n\n{message}\n\nAction by: {sender_name}\nOpen DengueWatch: {settings.SITE_BASE_URL}'
        html_body = (
            '<div style="font-family:Arial,sans-serif;line-height:1.6">'
            f'<h2>{escape(title)}</h2><p>{escape(message)}</p>'
            f'<p><strong>Action by:</strong> {escape(sender_name)}</p>'
            f'<p><a href="{escape(settings.SITE_BASE_URL)}">Open DengueWatch</a></p></div>'
        )
        try:
            outgoing = EmailMultiAlternatives(
                subject=f'DengueWatch: {title}',
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL or None,
                to=[recipient.email],
            )
            outgoing.attach_alternative(html_body, 'text/html')
            email_sent += outgoing.send(fail_silently=False)
        except Exception:
            email_failed += 1
            logger.exception('CHO workflow notification email failed for user id %s', recipient.pk)
    return {'email_sent': email_sent, 'email_failed': email_failed}
