"""Northstar company data and tools. The model never gets a database path or SQL access."""

import sqlite3
from pathlib import Path

from langchain_core.tools import ToolException
from tools import COMPANY_TOOLS, bind_company_tools

ROOT = Path(__file__).resolve().parent
ACCESS = {
    "sales": {"customer_brief", "send_proposal"},
    "engineering": {"customer_brief", "issue_lookup"},
    "finance": {"customer_brief", "revenue_summary"},
}


class Company:
    """Company data service. Role is bound by application code, never a model argument."""

    def __init__(self, database):
        """Open the company database and create missing tables and initial records."""
        self.access = {role: set(names) for role, names in ACCESS.items()}
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS customers
                    (id TEXT PRIMARY KEY, name TEXT, need TEXT, contact TEXT);
                CREATE TABLE IF NOT EXISTS issues
                    (id TEXT PRIMARY KEY, customer TEXT, symptom TEXT, owner TEXT);
                CREATE TABLE IF NOT EXISTS revenue
                    (quarter TEXT PRIMARY KEY, amount_usd INTEGER);
                CREATE TABLE IF NOT EXISTS outbox
                    (id TEXT PRIMARY KEY, customer TEXT, body TEXT);
            """)
            db.executemany("INSERT OR IGNORE INTO customers VALUES (?, ?, ?, ?)", [
                ("C-101", "Acme", "Unify weekly sales reporting across three teams", "buyer@acme.example"),
                ("C-102", "Beacon", "Investigate delayed dashboard refreshes", "ops@beacon.example"),
            ])
            db.execute("INSERT OR IGNORE INTO issues VALUES (?, ?, ?, ?)",
                       ("INC-42", "Beacon", "Sync stalls when the upstream API returns HTTP 429", "Data Platform"))
            db.execute("INSERT OR IGNORE INTO revenue VALUES (?, ?)", ("2026-Q3", 480000))

    def query(self, sql, parameters=()):
        """Run a parameterized read-only query and return rows as dictionaries."""
        with sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, parameters).fetchall()]

    def tools_for(self, role):
        """Return only the tools this application-selected role may use."""
        available = self.all_tools_for(role)
        return [value for name, value in available.items() if name in self.access[role]]

    def all_tools_for(self, role):
        """Bind each company tool to this role; unauthorized calls return an access denial."""
        if role not in self.access:
            raise ValueError(f"Unknown employee role: {role}")

        def require(name):
            """Reject tool access unless the bound employee role is authorized."""
            if name not in self.access[role]:
                raise ToolException(f"Access denied: {role} cannot use {name}.")

        tools = bind_company_tools(COMPANY_TOOLS, self, require)
        return {item.name: item for item in tools}

    def outbox(self):
        """Return proposals already recorded in the local outbox; no email is sent."""
        return self.query("SELECT * FROM outbox ORDER BY rowid")
