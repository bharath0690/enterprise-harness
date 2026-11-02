"""Send proposal."""
import hashlib
import sqlite3
from langchain_core.tools import ToolException
from langchain.tools import tool
from .binding import current_company


@tool
def send_proposal(customer: str, body: str) -> dict:
    """Record a customer proposal in the local outbox after human approval.

    Args:
        customer: Existing customer name, such as Acme.
        body: Proposal with Customer goal, Proposed scope, Assumptions, and Next steps.

    Returns:
        A receipt, customer name, and local-send status. Repeated identical
        proposals reuse the receipt. This tool does not send email."""
    company = current_company()
    rows = company.query("SELECT name FROM customers WHERE name = ? COLLATE NOCASE", (customer,))
    if not rows:
        raise ToolException("Unknown customer. Look up the customer before sending.")
    customer = rows[0]["name"]
    # A stable ID avoids duplicating the same outbox entry after a replay.
    key = hashlib.sha256(f"{customer}\0{body}".encode()).hexdigest()[:16]
    with sqlite3.connect(company.database) as db:
        db.execute("INSERT OR IGNORE INTO outbox VALUES (?, ?, ?)", (key, customer, body))
    return {"status": "simulated_send", "receipt": key, "customer": customer}
