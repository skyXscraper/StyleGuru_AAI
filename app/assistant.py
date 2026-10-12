import json
import os
import time

import httpx
from google import genai
from google.genai import errors, types

from . import catalog
MODELS = list(dict.fromkeys([
    os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
]))
COOLDOWN_SECONDS = 120
_resting_until = {}  
REQUEST_TIMEOUT_MS = 30_000
MAX_TOOL_ROUNDS = 4
MAX_CARDS = 12

SYSTEM_PROMPT = """You are StyleGuru, the virtual shopping assistant of an Indian fashion retailer.
You help customers find clothes, footwear and accessories from the store's catalogue. Prices are in ₹.

How to work:
- Always call search_products to find products. Never invent products, prices or stock;
  only talk about products the tool returned.
- Search straight away when you have something to go on. Ask one short clarifying question
  only when the request is too vague to search at all.
- When the customer sends a photo, work out the item's type, colour and style, then search
  for similar products. If they ask what goes with it, search for complementary product types
  instead (for example shoes and trousers for a shirt).
- For a full outfit, call search_products once per product type.
- Carry requirements over from earlier in the conversation (budget, size, colour, occasion)
  unless the customer changes them.
- Be honest about availability. If the tool returns notes or sold-out items, say so and
  point to the closest in-stock alternative.

Privacy:
- If a photo shows a person, describe only the clothing. Never comment on the person's
  identity, face, body, age or any other personal trait.
- Never ask for personal details such as name, phone number, address or payment information.

Style: reply in 2 to 4 short, friendly sentences of plain text with no markdown and no lists.
Mention at most three products by name with their price; the app shows the full results
as cards next to the chat."""

SEARCH_TOOL = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="search_products",
    description=(
        "Search the store catalogue. Returns in-stock matches ranked for this customer, "
        "sold-out near-misses, and notes about anything that could not be matched. "
        "Only set the filters the customer actually asked for."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "product_types": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": catalog.PRODUCT_TYPES},
                "description": "Kinds of product to include.",
            },
            "gender": {"type": "STRING", "enum": ["Men", "Women"]},
            "colours": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Plain colour names, e.g. 'navy blue', 'black'.",
            },
            "occasion": {
                "type": "STRING",
                "enum": catalog.OCCASIONS,
                "description": "Weddings and festivals are Ethnic; office and interviews are Formal.",
            },
            "min_price": {"type": "INTEGER", "description": "Minimum price in rupees."},
            "max_price": {"type": "INTEGER", "description": "Maximum price in rupees."},
            "size": {
                "type": "STRING",
                "description": "Clothing size S, M, L, XL or XXL, or a UK shoe size such as 8.",
            },
            "keywords": {
                "type": "STRING",
                "description": "Other words to look for in product names, e.g. brand or pattern.",
            },
        },
    },
)])


def _profile_summary(profile):
    liked = [catalog.BY_ID[i]["name"] for i in profile.get("liked") or [] if i in catalog.BY_ID]
    facts = {
        "shops for": profile.get("gender"),
        "clothing size": profile.get("size"),
        "shoe size (UK)": profile.get("shoe_size"),
        "usual budget per item (₹)": profile.get("budget"),
        "favourite colours": ", ".join(profile.get("colours") or []),
        "liked products": "; ".join(liked[-5:]),
    }
    lines = [f"- {label}: {value}" for label, value in facts.items() if value]
    if not lines:
        return ""
    return (
        "\n\nThe customer's saved style profile (search results are already ranked with it; "
        "use it as a default, but anything said in the chat wins):\n" + "\n".join(lines)
    )


def _for_model(result):
    """A compact view of a search result, to keep the prompt small."""
    def brief(product):
        return {
            "id": product["id"],
            "name": product["name"],
            "type": product["type"],
            "colour": product["colour"],
            "occasion": product["occasion"],
            "price": product["price"],
            "sizes_in_stock": [size for size, left in product["stock"].items() if left],
        }
    return {
        "results": [brief(p) for p in result["results"]],
        "sold_out": [brief(p) for p in result["unavailable"]],
        "notes": result["notes"],
    }


async def _run_turn(client, model, contents, config, profile):
    """Let the model search the catalogue until it is ready to answer."""
    products, searches = {}, []
    response = None
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.aio.models.generate_content(model=model, contents=contents, config=config)
        calls = response.function_calls
        if not calls:
            break
        contents.append(response.candidates[0].content)
        answers = []
        for call in calls:
            filters = catalog.normalise(dict(call.args or {}))
            result = catalog.search(filters, profile)
            searches.append(filters)
            for product in result["results"] + result["unavailable"]:
                products.setdefault(product["id"], product)
            answers.append(types.Part.from_function_response(name=call.name, response=_for_model(result)))
        contents.append(types.Content(role="user", parts=answers))
    return response, products, searches


async def chat(message, history, profile=None, image=None):
    """Run one turn of the conversation.

    `history` is a list of {"role": "user" | "assistant", "text": str, "note": str} from
    earlier turns, `profile` is None when personalisation is off, and `image` is JPEG bytes
    or None.
    """
    last_note = next((turn["note"] for turn in reversed(history) if turn.get("note")), "")
    on_screen = f"\n\nYour most recent search in this conversation:\n{last_note}" if last_note else ""
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + _profile_summary(profile or {}) + on_screen,
        tools=[SEARCH_TOOL],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.4,
    )

    contents = [
        types.Content(
            role="model" if turn["role"] == "assistant" else "user",
            parts=[types.Part(text=turn["text"])],
        )
        for turn in history
    ]
    parts = [types.Part.from_bytes(data=image, mime_type="image/jpeg")] if image else []
    parts.append(types.Part(text=message))
    contents.append(types.Content(role="user", parts=parts))

    now = time.monotonic()
    available = [m for m in MODELS if _resting_until.get(m, 0) <= now] or MODELS
    for model in available:
        try:
            response, products, searches = await _run_turn(client, model, list(contents), config, profile)
            break
        except (errors.APIError, httpx.TimeoutException) as error:
            retryable = isinstance(error, httpx.TimeoutException) or error.code in (429, 500, 503)
            if not retryable:
                raise
            _resting_until[model] = now + COOLDOWN_SECONDS
            if model == available[-1]:
                raise

    reply = (response.text or "").strip() or "Sorry, I couldn't put together an answer. Could you rephrase that?"
    shown = sorted(products.values(), key=lambda p: not p["available"])[:MAX_CARDS]

    note = ""
    if searches:
        names = "\n".join(
            f"{number}. {p['name']}, ₹{p['price']}{'' if p['available'] else ', sold out'}"
            for number, p in enumerate(shown, 1)
        )
        note = f"Filters: {json.dumps(searches)}\nProducts shown to the customer, in order:\n{names}"

    return {
        "reply": reply,
        "products": shown if searches else None,
        "filters": searches[0] if searches else None,
        "note": note,  # the browser sends this back with the next message
    }
