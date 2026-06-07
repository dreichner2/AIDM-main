from __future__ import annotations

from flask import jsonify


def clamp_limit(limit: int | None, *, maximum: int = 500) -> int | None:
    if limit is None:
        return None
    return max(1, min(maximum, int(limit)))


def limited_page(query, *, limit: int | None):
    page_limit = clamp_limit(limit)
    if page_limit is None:
        return PageItems(query.all(), has_more=False)
    rows = query.limit(page_limit + 1).all()
    return PageItems(rows[:page_limit], has_more=len(rows) > page_limit)


def jsonify_page(items, *, payload_for, cursor_for):
    response = jsonify([payload_for(item) for item in items])
    response.headers['X-AIDM-Has-More'] = 'true' if getattr(items, '_has_more', False) else 'false'
    if getattr(items, '_has_more', False) and items:
        response.headers['X-AIDM-Next-Cursor'] = str(cursor_for(items[-1]))
    return response


class PageItems(list):
    def __init__(self, rows, *, has_more: bool):
        super().__init__(rows)
        self._has_more = has_more
