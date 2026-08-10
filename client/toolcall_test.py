#!/usr/bin/env python3
"""
Tool-calling smoke test for a local Ollama model.

Proves the full loop the MCP client depends on:
  1. Send the model a user question + a tool schema.
  2. Model emits a valid tool call (name + args).
  3. We run the "tool" locally and feed the result back.
  4. Model produces a final natural-language answer using that result.

If step 2 fails, the model can't drive the client -> pick another model.
This transcript goes into the design doc (Chat model section).

Run:
  pip install ollama
  python3 toolcall_test.py
"""

import json
import ollama

MODEL = "qwen2.5:7b-instruct"  # swap to test others: llama3.1:8b, mistral:latest

# --- Fake retail "record" tool. Stands in for a real MCP server tool. ---
INVENTORY = {
    "SKU12345": {"name": "Wireless Headphones", "price": 79.99, "stock": 42},
    "SKU88123": {"name": "4K Action Camera", "price": 249.00, "stock": 0},
}

def lookup_product(sku: str) -> dict:
    """Local implementation the client runs when the model asks for it."""
    return INVENTORY.get(sku, {"error": f"SKU {sku} not found"})

# --- Tool schema advertised to the model (MCP-style: name/description/params) ---
TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_product",
        "description": "Look up a retail product's name, price, and stock by SKU.",
        "parameters": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Product SKU, e.g. SKU12345"}
            },
            "required": ["sku"],
        },
    },
}]

def main():
    question = "How many Wireless Headphones (SKU12345) are in stock, and what's the price?"
    messages = [
        {"role": "system", "content": "You are a retail assistant. Use tools to look up product data. Never guess stock or price."},
        {"role": "user", "content": question},
    ]

    print(f"MODEL: {MODEL}")
    print(f"USER: {question}\n")

    # --- Turn 1: model should request the tool ---
    resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
    msg = resp["message"]
    calls = msg.get("tool_calls")

    if not calls:
        print("FAIL: model did not emit a tool call. Raw reply:")
        print(msg.get("content", "<empty>"))
        print("\n-> This model is unreliable for tool-calling. Try another.")
        return

    call = calls[0]
    fn = call["function"]["name"]
    args = call["function"]["arguments"]
    if isinstance(args, str):
        args = json.loads(args)
    print(f"TOOL CALL: {fn}({args})")

    # --- Run the tool, feed result back ---
    result = lookup_product(**args)
    print(f"TOOL RESULT: {result}\n")

    messages.append(msg)
    messages.append({"role": "tool", "content": json.dumps(result)})

    # --- Turn 2: model answers using the tool result ---
    final = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
    print("FINAL ANSWER:")
    print(final["message"]["content"])
    print("\nPASS: full tool-call loop worked.")

if __name__ == "__main__":
    main()
