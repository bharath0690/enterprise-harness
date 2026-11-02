# NS Work tools

## Company tools

| Tool | Purpose | Input | Access | Source |
| --- | --- | --- | --- | --- |
| `customer_brief` | Read a customer’s goal and contact | Customer name | Sales, engineering, finance | `tools/customer.py` |
| `issue_lookup` | Read an engineering issue’s symptom and owner | Customer name | Engineering | `tools/issues.py` |
| `revenue_summary` | Read a quarter’s revenue total | Quarter, such as `2026-Q3` | Finance | `tools/revenue.py` |
| `send_proposal` | Record an approved proposal in the local outbox | Customer name and body | Sales | `tools/proposals.py` |

Each tool file starts with its named `@tool` function. `tools/binding.py` connects these definitions to company data and access checks. `company.py` owns database access and role assignment. The model does not supply its own role.

## Harness tools

- **Working files:** `read_file`, `write_file`, and `edit_file` let the model read procedures and maintain drafts. These file capabilities come from Deep Agents.
- **Planning:** `write_todos` updates the plan. It is enabled through `TodoListMiddleware` in `agent.py`.
- **Delegation:** `task` sends a narrower job to the configured proposal reviewer. The reviewer has customer lookup but no sending tool.

A skill is a procedure, not another company API. The proposal skill is loaded with `read_file`, then its instructions guide the use of company tools.

## Boundaries around tools

`agent.py` configures approval before `send_proposal`. The send implementation stores a local outbox record; it does not send email. Access rules and approval serve different purposes.
