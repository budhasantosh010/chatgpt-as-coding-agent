"""Codex-style task layer: the unit of identity, persistence, and permission.

A Task owns a workspace, permission mode, plan, and lifecycle state, and is the
explicit handle (task_id) that makes concurrent ChatGPT conversations isolated —
identity lives here, not in the HTTP connection.
"""
