import os
from typing import Optional
from datetime import datetime


def _get_api_key() -> str:
    from providers import get_provider_api_key
    return get_provider_api_key()


# -- Advanced search modes ---------------------------------------------------

def _news_search(query: str) -> str:
    """Search for recent news articles using Gemini Grounded Search."""
    news_query = f"recent news articles about {query}"
    try:
        return _gemini_search(news_query)
    except Exception as e:
        print(f"[WebSearch] Gemini news search failed: {e} -- falling back to DDG")
        results = _ddg_search(f"news {query}", max_results=6)
        return _format_ddg(f"news: {query}", results)


def _research_search(query: str) -> str:
    """Search for in-depth research and analysis."""
    research_query = f"detailed research and analysis about {query}"
    try:
        return _gemini_search(research_query)
    except Exception as e:
        print(f"[WebSearch] Gemini research search failed: {e} -- falling back to DDG")
        results = _ddg_search(f"research {query}", max_results=6)
        return _format_ddg(f"research: {query}", results)


def _price_search(query: str) -> str:
    """Search for pricing information."""
    price_query = f"current prices and pricing information for {query}"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        print(f"[WebSearch] Gemini price search failed: {e} -- falling back to DDG")
        results = _ddg_search(f"price {query}", max_results=6)
        return _format_ddg(f"price: {query}", results)


def _gemini_search(query: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    from actions.quota_tracker import increment as increment_quota
    increment_quota()
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):
            lines.append(f"{i}. {r['title']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] Gemini compare failed: {e} -- falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison -- {aspect.upper()}", "-" * 40]
    for item in items:
        lines.append(f"\n> {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  * {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


def web_search(
    parameters: dict,
    speak=None,
) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode = params.get("mode", "search").lower().strip()
    items = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    print(f"[WebSearch] mode={mode!r} query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        elif mode == "news":
            return _news_search(query)
        elif mode == "research":
            return _research_search(query)
        elif mode == "price":
            return _price_search(query)
        else:
            try:
                result = _gemini_search(query)
                print("[WebSearch] Gemini OK.")
                return result
            except Exception as e:
                print(f"[WebSearch] Gemini failed ({e}) -- trying DDG...")
                results = _ddg_search(query)
                result = _format_ddg(query, results)
                print(f"[WebSearch] DDG: {len(results)} result(s).")
                return result

    except Exception as e:
        print(f"[WebSearch] All backends failed: {e}")
        return f"Search failed: {e}"
