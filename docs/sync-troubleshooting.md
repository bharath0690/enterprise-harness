# Data sync troubleshooting runbook

## Rate limits from upstream APIs
When an upstream API returns HTTP 429, the connector backs off exponentially, starting at 30 seconds and capping at 15 minutes.
Repeated 429 responses can make a sync appear stalled even though it is waiting.
First check: open the connector log and count 429 responses in the last hour.
If the count exceeds 50, ask the customer to raise their API quota or reduce the sync frequency.

## Stale dashboards
Dashboards refresh after each successful sync. A dashboard older than two sync intervals indicates a failed or delayed sync.
Check the last successful sync time before changing any dashboard query.

## Ownership
Connector and sync issues belong to the Data Platform team.
Dashboard rendering issues belong to the Dashboards team.
