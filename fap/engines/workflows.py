"""A small, deterministic workflow engine.

The original product exposes a visual flow editor with trigger / wait / extract
/ API / condition / delay / deliver / notify nodes.  This clone implements the
synchronous subset that can be executed without a live platform connection:

    trigger, set, extract, api, condition, delay, deliver, notify

Flows are stored as ``nodes`` (list) + ``edges`` (list of {from,to,when}) and
every run records one row in ``workflow_runs`` plus one row per executed node in
``workflow_steps``.
"""

from __future__ import annotations

import json
import time

import httpx

from .. import db, notify
from .common import render

MAX_STEPS = 50
MAX_DELAY = 5.0

NODE_TYPES = {
    "trigger", "set", "extract", "api", "condition", "delay", "deliver", "notify",
}


class WorkflowError(Exception):
    pass


def validate(nodes: list[dict], edges: list[dict]) -> list[str]:
    errors: list[str] = []
    ids = [n.get("id") for n in nodes]
    if not nodes:
        errors.append("流程至少需要一个节点")
    if len(set(ids)) != len(ids):
        errors.append("节点 id 不能重复")
    for n in nodes:
        if not n.get("id"):
            errors.append("存在缺少 id 的节点")
        if n.get("type") not in NODE_TYPES:
            errors.append(f"节点 {n.get('id')} 类型不支持: {n.get('type')}")
    idset = {i for i in ids if i}
    for e in edges:
        if e.get("from") not in idset or e.get("to") not in idset:
            errors.append(f"连线引用了不存在的节点: {e}")
    return errors


def _out_edges(edges: list[dict], node_id: str, when: str | None = None) -> list[dict]:
    out = [e for e in edges if e.get("from") == node_id]
    if when is None:
        return [e for e in out if not e.get("when") or e.get("when") == "always"]
    return [e for e in out if e.get("when") == when]


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text not in ("", "0", "false", "no", "off", "null", "none")


def _eval_condition(node: dict, ctx: dict) -> bool:
    left = render(str(node.get("left", "")), ctx)
    right = render(str(node.get("right", "")), ctx)
    op = node.get("op", "==")
    try:
        if op in (">", "<", ">=", "<="):
            lv, rv = float(left), float(right)
        else:
            lv, rv = left, right
    except ValueError:
        lv, rv = left, right
    if op == "==":
        return str(lv) == str(rv)
    if op == "!=":
        return str(lv) != str(rv)
    if op == ">":
        return lv > rv
    if op == "<":
        return lv < rv
    if op == ">=":
        return lv >= rv
    if op == "<=":
        return lv <= rv
    if op == "contains":
        return str(rv) in str(lv)
    if op == "not_contains":
        return str(rv) not in str(lv)
    raise WorkflowError(f"未知条件运算符: {op}")


def _run_node(conn, node: dict, ctx: dict) -> tuple[bool, str]:
    kind = node.get("type")
    if kind == "trigger":
        return True, "triggered"
    if kind == "set":
        ctx[str(node.get("key", ""))] = render(str(node.get("value", "")), ctx)
        return True, f"set {node.get('key')}"
    if kind == "extract":
        source = node.get("text") or f"{{{{{node.get('source', '')}}}}}"
        text = render(str(source), ctx)
        pattern = node.get("pattern", "")
        try:
            import re

            m = re.search(pattern, text)
        except re.error as exc:
            raise WorkflowError(f"提取正则无效: {exc}") from exc
        if not m:
            if node.get("optional"):
                return True, "extract skipped"
            raise WorkflowError(f"提取失败，未匹配到内容: {pattern}")
        group = int(node.get("group", 1) or 0)
        try:
            value = m.group(group)
        except IndexError:
            value = m.group(0)
        ctx[str(node.get("key", "value"))] = value
        return True, f"extracted {value}"
    if kind == "api":
        url = render(str(node.get("url", "")), ctx)
        method = str(node.get("method", "POST")).upper()
        headers = {str(k): render(str(v), ctx) for k, v in (node.get("headers") or {}).items()}
        body = node.get("body")
        if isinstance(body, str):
            body = render(body, ctx)
        elif isinstance(body, dict):
            body = {str(k): render(str(v), ctx) for k, v in body.items()}
        timeout = float(node.get("timeout", 10))
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, headers=headers, json=body if isinstance(body, dict) else None,
                                  content=body if isinstance(body, str) and body else None)
        text = resp.text
        ctx[str(node.get("save", "api_response"))] = text
        if resp.status_code >= 400 and not node.get("allow_failure"):
            raise WorkflowError(f"API 返回 {resp.status_code}: {text[:200]}")
        return True, f"HTTP {resp.status_code}"
    if kind == "condition":
        ok = _eval_condition(node, ctx)
        ctx["_last_condition"] = ok
        return True, "true" if ok else "false"
    if kind == "delay":
        seconds = min(max(float(node.get("seconds", 1)), 0), MAX_DELAY)
        time.sleep(seconds)
        return True, f"waited {seconds}s"
    if kind == "deliver":
        content = render(str(node.get("content", "")), ctx)
        if node.get("append") and ctx.get("delivery"):
            ctx["delivery"] = str(ctx["delivery"]) + "\n" + content
        else:
            ctx["delivery"] = content
        return True, "delivery prepared"
    if kind == "notify":
        message = render(str(node.get("message", "")), ctx)
        ctx.setdefault("notifications", []).append(message)
        try:
            notify.dispatch(conn, "workflow.notify", "流程通知", message,
                            ctx.get("account_id"))
        except Exception:
            pass
        return True, message
    raise WorkflowError(f"节点类型不支持: {kind}")


def run_workflow(conn, workflow: dict, context: dict, order_id: int | None = None) -> dict:
    nodes = json.loads(workflow.get("nodes_json") or "[]")
    edges = json.loads(workflow.get("edges_json") or "[]")
    errors = validate(nodes, edges)
    if errors:
        raise WorkflowError("; ".join(errors))

    run_cur = conn.execute(
        "INSERT INTO workflow_runs(workflow_id, order_id, status, context_json, started_at) "
        "VALUES(?,?,?,?,?)",
        (workflow["id"], order_id, "running", json.dumps(context, ensure_ascii=False), db.now_iso()),
    )
    run_id = int(run_cur.lastrowid)
    by_id = {n["id"]: n for n in nodes}
    current = next((n for n in nodes if n.get("type") == "trigger"), nodes[0])
    visited: dict[str, int] = {}
    try:
        for _ in range(MAX_STEPS):
            visited[current["id"]] = visited.get(current["id"], 0) + 1
            if visited[current["id"]] > 5:
                raise WorkflowError(f"检测到循环: {current['id']}")
            try:
                ok, output = _run_node(conn, current, context)
                status = "ok"
            except Exception as exc:  # record and re-raise after persisting
                conn.execute(
                    "INSERT INTO workflow_steps(run_id, node_id, node_type, status, output, created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (run_id, current["id"], current.get("type", ""), "failed", str(exc), db.now_iso()),
                )
                raise
            conn.execute(
                "INSERT INTO workflow_steps(run_id, node_id, node_type, status, output, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, current["id"], current.get("type", ""), status, output, db.now_iso()),
            )
            conn.commit()
            if current.get("type") == "condition":
                branch = "true" if context.get("_last_condition") else "false"
                candidates = _out_edges(edges, current["id"], branch)
                if not candidates:
                    candidates = _out_edges(edges, current["id"], None)
            else:
                candidates = _out_edges(edges, current["id"], None)
            if not candidates:
                break
            current = by_id.get(candidates[0]["to"])
            if not current:
                break
        conn.execute(
            "UPDATE workflow_runs SET status=?, context_json=?, finished_at=? WHERE id=?",
            ("ok", json.dumps(context, ensure_ascii=False, default=str), db.now_iso(), run_id),
        )
        conn.commit()
        return {"run_id": run_id, "status": "ok", "context": context}
    except Exception as exc:
        conn.execute(
            "UPDATE workflow_runs SET status=?, context_json=?, error=?, finished_at=? WHERE id=?",
            ("failed", json.dumps(context, ensure_ascii=False, default=str), str(exc), db.now_iso(), run_id),
        )
        conn.commit()
        return {"run_id": run_id, "status": "failed", "error": str(exc), "context": context}
