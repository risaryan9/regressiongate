"""Fake support tools. Data is hard-coded so eval runs are reproducible."""

from datetime import date

from tracing.trace import trace

# Fixed "today" so refund-window answers don't drift as real time passes.
TODAY = date(2026, 10, 15)
REFUND_WINDOW_DAYS = 30

ORDERS = {
    "A1001": {"item": "Wireless headphones", "total": 89.99, "status": "delivered", "delivered_on": "2026-10-05"},
    "A1002": {"item": "Coffee grinder", "total": 45.00, "status": "delivered", "delivered_on": "2026-08-20"},
    "A1003": {"item": "Standing desk", "total": 399.00, "status": "shipped", "delivered_on": None},
    "A1004": {"item": "Phone case", "total": 19.99, "status": "delivered", "delivered_on": "2026-09-01"},
}

_escalations: list[dict] = []


@trace(kind="tool")
def lookup_order(order_id: str) -> dict:
    order = ORDERS.get(order_id.strip().upper())
    if order is None:
        return {"found": False, "order_id": order_id}
    return {"found": True, "order_id": order_id.upper(), **order}


@trace(kind="tool")
def check_refund_policy(order_id: str, reason: str) -> dict:
    order = ORDERS.get(order_id.strip().upper())
    if order is None:
        return {"eligible": False, "why": "order not found"}
    if order["status"] != "delivered":
        return {"eligible": False, "why": "order not delivered yet"}
    if "damaged" in reason.lower() or "broken" in reason.lower():
        return {"eligible": True, "why": "damaged items are always refundable"}
    days = (TODAY - date.fromisoformat(order["delivered_on"])).days
    if days <= REFUND_WINDOW_DAYS:
        return {"eligible": True, "why": f"within {REFUND_WINDOW_DAYS}-day window ({days} days)"}
    return {"eligible": False, "why": f"outside {REFUND_WINDOW_DAYS}-day window ({days} days)"}


@trace(kind="tool")
def escalate(summary: str, priority: str = "normal") -> dict:
    ticket_id = f"ESC-{len(_escalations) + 1:04d}"
    _escalations.append({"id": ticket_id, "summary": summary, "priority": priority})
    return {"escalated": True, "escalation_id": ticket_id, "priority": priority}


TOOL_FUNCS = {"lookup_order": lookup_order, "check_refund_policy": check_refund_policy, "escalate": escalate}

TOOL_SCHEMAS = [
    {
        "name": "lookup_order",
        "description": "Look up an order by its ID (e.g. A1001). Returns item, total, status, delivery date.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "check_refund_policy",
        "description": "Check whether an order is eligible for a refund given the customer's reason.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["order_id", "reason"],
        },
    },
    {
        "name": "escalate",
        "description": "Hand the ticket to a human agent. Use for anger, legal threats, or anything you can't resolve.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            },
            "required": ["summary"],
        },
    },
]
