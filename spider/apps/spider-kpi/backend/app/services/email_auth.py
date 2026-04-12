from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()
VERIFICATION_CODE_TTL_MINUTES = 15
VERIFICATION_CODE_LENGTH = 6


def generate_verification_code() -> str:
    return ''.join(secrets.choice('0123456789') for _ in range(VERIFICATION_CODE_LENGTH))


def verification_code_hash(email: str, code: str) -> str:
    normalized = f"{email.strip().lower()}::{code.strip()}::{settings.jwt_secret}"
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def verification_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)


def send_email_verification_code(recipient_email: str, code: str) -> None:
    sender = settings.auth_email_from
    if not sender:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Email verification is not configured yet')

    subject = 'Your access code'
    body_text = (
        'Use the verification code below to continue signing in.\n\n'
        f'{code}\n\n'
        f'This code expires in {VERIFICATION_CODE_TTL_MINUTES} minutes. If you did not request it, you can ignore this email.'
    )
    body_html = (
        '<html><body style="font-family:Arial,sans-serif;color:#111827;line-height:1.5">'
        '<p>Use the verification code below to continue signing in.</p>'
        f'<p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>'
        f'<p>This code expires in {VERIFICATION_CODE_TTL_MINUTES} minutes. If you did not request it, you can ignore this email.</p>'
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
