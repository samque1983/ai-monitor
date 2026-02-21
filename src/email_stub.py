import logging

logger = logging.getLogger(__name__)


def send_email(report_text: str, config=None):
    """Send report via email.

    TODO: Implement with smtplib when ready.

    Usage:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(report_text)
        msg['Subject'] = 'V1.9 Quant Radar Report'
        msg['From'] = config['email']['from']
        msg['To'] = config['email']['to']

        with smtplib.SMTP(config['email']['smtp_host'], config['email']['smtp_port']) as server:
            server.starttls()
            server.login(config['email']['username'], config['email']['password'])
            server.send_message(msg)
    """
    logger.info("Email sending not configured. Report printed to stdout only.")
