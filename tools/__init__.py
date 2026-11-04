"""Company operations and their application-owned binding."""
from .customer import customer_brief
from .issues import issue_lookup
from .revenue import revenue_summary
from .proposals import send_proposal
from .docs import search_docs
from .binding import bind_company_tools

COMPANY_TOOLS = (customer_brief, search_docs, issue_lookup, revenue_summary, send_proposal)
