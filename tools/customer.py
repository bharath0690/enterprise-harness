"""Customer lookup."""
from langchain.tools import tool
from .binding import current_company


@tool
def customer_brief(customer: str) -> list[dict]:
    """Look up a customer’s recorded goal and contact before answering or drafting.

    Args:
        customer: Company name, such as Acme. Use the name, not a record ID.

    Returns:
        Matching records with id, name, need, and contact; an empty list if unknown.
        Cite the record ID when using these facts. This tool does not change data."""
    company = current_company()
    return company.query("SELECT * FROM customers WHERE name = ? COLLATE NOCASE", (customer,))
