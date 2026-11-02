"""Revenue summary."""
from langchain.tools import tool
from .binding import current_company


@tool
def revenue_summary(quarter: str) -> list[dict]:
    """Read the recorded revenue total for a quarter, without estimating missing data.

    Args:
        quarter: Reporting quarter in YYYY-QN form, such as 2026-Q3.

    Returns:
        The quarter and amount_usd, or an empty list when no record exists.
        Available to finance. This tool does not modify financial records."""
    company = current_company()
    return company.query("SELECT * FROM revenue WHERE quarter = ?", (quarter,))
