"""
Module 1: State Schema (state.py)

Concept: The SREState is the "shared notebook" carried between every node in the graph.
Why TypedDict? It enforces strict typing for all keys in the state.
Why add_messages? It tells LangGraph to APPEND new messages to the list rather than overwriting them.
"""

from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class SREState(TypedDict):
    # The message history between user and agent (appended on every update)
    messages: Annotated[list, add_messages]
    
    # Target microservice currently being investigated
    target_service: str
    
    # Current status of the investigation
    status: str
    
    # Proposed remediation patch (e.g. YAML fix)
    proposed_patch: str
