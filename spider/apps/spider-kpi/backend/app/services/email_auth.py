from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()
VERIFICATION_TOKEN_TTL_MINUTES = 60  # 1 hour for link-based verification
VERIFICATION_TOKEN_BYTES = 32  # 43 chars URL-safe


def generate_verification_token() -> str:
    return secrets.token_urlsafe(VERIFICATION_TOKEN_BYTES)


def verification_token_hash(token: str) -> str:
    normalized = f"{token.strip()}::{settings.jwt_secret}"
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def verification_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_TOKEN_TTL_MINUTES)


def _build_verify_url(token: str) -> str:
    """Build the verification URL that the user clicks in the email."""
    # Use the frontend origin — the backend serves at the same origin
    base = 'https://kpi.spidergrills.com'
    if settings.env == 'development':
        base = 'http://localhost:8000'
    return f'{base}/api/auth/verify-email?token={token}'


def send_verification_email(recipient_email: str, token: str) -> None:
    sender = settings.auth_email_from
    if not sender:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Email verification is not configured yet')

    verify_url = _build_verify_url(token)
    subject = 'Verify your Spider Grills KPI Dashboard account'
    body_text = (
        'Welcome to the Spider Grills KPI Dashboard!\n\n'
        'Click the link below to verify your email address and activate your account:\n\n'
        f'{verify_url}\n\n'
        f'This link expires in {VERIFICATION_TOKEN_TTL_MINUTES} minutes.\n'
        'If you did not create this account, you can ignore this email.'
    )
    body_html = (
        '<html><body style="font-family:Arial,sans-serif;color:#111827;line-height:1.6;max-width:480px;margin:0 auto;padding:24px">'
        '<div style="text-align:center;margin-bottom:24px">'
        '<h2 style="margin:0;color:#111827">Spider Grills KPI Dashboard</h2>'
        '</div>'
        '<p>Welcome! Click the button below to verify your email address and activate your account.</p>'
        f'<div style="text-align:center;margin:28px 0">'
        f'<a href="{verify_url}" style="display:inline-block;background:linear-gradient(135deg,#4a7aff,#5a8dff);'
        f'color:#fff;text-decoration:none;padding:14px 32px;border-radius:12px;font-weight:700;font-size:15px">'
        f'Verify my email</a></div>'
        '<p style="color:#6b7280;font-size:13px">Or copy and paste this link into your browser:</p>'
        f'<p style="color:#6b7280;font-size:12px;word-break:break-all">{verify_url}</p>'
        f'<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">'
        f'<p style="color:#9ca3af;font-size:12px">This link expires in {VERIFICATION_TOKEN_TTL_MINUTES} minutes. '
        f'If you did not create this account, you can ignore this email.</p>'
        '</body></html>'
    )

    client = boto3.client(
        'sesv2',
        region_name=settings.auth_email_region or settings.aws_region or 'us-east-2',
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    try:
        client.send_email(
            FromEmailAddress=sender,
            Destination={'ToAddresses': [recipient_email]},
            Content={
                'Simple': {
                    'Subject': {'Data': subject},
                    'Body': {
                        'Text': {'Data': body_text},
                        'Html': {'Data': body_html},
                    },
                }
            },
        )
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Unable to send verification email right now') from exc
