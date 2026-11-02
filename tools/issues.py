"""Issue lookup."""
from langchain.tools import tool
from .binding import current_company


@tool
def issue_lookup(customer: str) -> list[dict]:
    """Look up a customer’s reported engineering issue to guide investigation.

    Args:
        customer: Company name, such as Beacon.

    Returns:
        Matching issue IDs, symptoms, and owners; an empty list if none exist.
        Available to engineering. This lookup does not resolve or modify issues."""
    company = current_company()
    return company.query("SELECT * FROM issues WHERE customer = ? COLLATE NOCASE", (customer,))
