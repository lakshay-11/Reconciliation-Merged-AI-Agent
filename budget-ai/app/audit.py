import logging

logger = logging.getLogger("budget_audit")
handler = logging.FileHandler("budget_audit.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def audit_action(action: str, details: dict):
    logger.info(f"action={action} details={details}")
