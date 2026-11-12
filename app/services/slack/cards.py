"""Block Kit cards from the design."""

import json


def new_card(
    channel: str,
    request_id: str,
    title: str,
    system_source: str,
    expires_at: str,
    details: dict[str, str] | None,
) -> str:
    blocks: list[object] = [_header(title)]
    detail_block = _details(details)
    if detail_block is not None:
        blocks.append(detail_block)
    blocks.append(_actions(request_id))
    blocks.append(_context(request_id, system_source, expires_at))
    return _dump(
        {
            "channel": channel,
            "text": title,
            "metadata": {
                "event_type": "approval_request",
                "event_payload": {"request_id": request_id},
            },
            "blocks": blocks,
        }
    )


def terminal_card(
    channel: str,
    message_ts: str,
    title: str,
    request_id: str,
    system_source: str,
    expires_at: str,
    status: str,
    decided_by: str | None,
    decided_at: str | None,
) -> str:
    return _dump(
        {
            "channel": channel,
            "ts": message_ts,
            "text": title,
            "blocks": [
                _header(title),
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": _terminal_text(status, decided_by, decided_at, expires_at),
                    },
                },
                _context(request_id, system_source, expires_at),
            ],
        }
    )


def replaced_card(channel: str, message_ts: str) -> str:
    text = "This approval card was replaced by a newer request with the same ID."
    return _dump(
        {
            "channel": channel,
            "ts": message_ts,
            "text": text,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        }
    )


def _terminal_text(
    status: str, decided_by: str | None, decided_at: str | None, expires_at: str
) -> str:
    if status == "approved":
        return f"Approved by {decided_by} at {decided_at}."
    if status == "rejected":
        return f"Rejected by {decided_by} at {decided_at}."
    return f"This approval request expired at {expires_at}."


def _header(title: str) -> dict[str, object]:
    return {"type": "header", "text": {"type": "plain_text", "text": title}}


def _details(details: dict[str, str] | None) -> dict[str, object] | None:
    if not details:
        return None
    fields: list[object] = []
    for key, value in list(details.items())[:10]:
        fields.append({"type": "mrkdwn", "text": f"*{key}*\n{value}"})
    return {"type": "section", "fields": fields}


def _actions(request_id: str) -> dict[str, object]:
    return {
        "type": "actions",
        "block_id": "approval_actions",
        "elements": [
            {
                "type": "button",
                "action_id": "approve_request",
                "style": "primary",
                "text": {"type": "plain_text", "text": "Approve"},
                "value": request_id,
            },
            {
                "type": "button",
                "action_id": "reject_request",
                "style": "danger",
                "text": {"type": "plain_text", "text": "Reject"},
                "value": request_id,
            },
        ],
    }


def _context(request_id: str, system_source: str, expires_at: str) -> dict[str, object]:
    text = f"{request_id} · {system_source} · expires {expires_at}"
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _dump(body: dict[str, object]) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))
