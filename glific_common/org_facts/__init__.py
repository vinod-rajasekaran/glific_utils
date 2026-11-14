"""The cleaned facts about an account's flows, shared by the org map and the MCP server.

model.Model reads an export (flows, triggers, organisation settings): how each flow starts,
what it leads to, what it touches. facts.build_facts turns that into the cleaned facts sent to
Claude, with staff names, phone numbers, emails and links masked. grouping groups flows by their
links, without Claude.
"""
