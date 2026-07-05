"""Token + cost accounting for the SEO blog swarm.

Accumulates per-agent text-model usage and image-generation counts from a run,
then renders a breakdown grouped into Content / Deploy / Images with an estimated
total. Rates come from pricing.json (edit that file with your real prices).
"""

import json
from pathlib import Path

_PRICING_PATH = Path(__file__).with_name("pricing.json")

# Which pipeline bucket each agent's text tokens belong to.
_CONTENT_AGENTS = {"SEO Director", "SEO Research Agent", "Blog Writer"}
_IMAGE_AGENTS = {"Blog Image Agent"}
_DEPLOY_AGENTS = {"Blog Deploy Agent"}


def load_pricing(path: Path = _PRICING_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"rates_are_examples": True, "text_per_1m_tokens": {}, "image_per_image": {}}


def _rate(table: dict, model: str) -> dict:
    """Resolve a model to its rate row: exact match, then prefix, then 'default'."""
    if not model:
        return table.get("default", {})
    if model in table:
        return table[model]
    for key, row in table.items():
        if key not in ("default",) and model.startswith(key):
            return row
    return table.get("default", {})


def _money(x: float) -> str:
    return f"${x:,.4f}"


def _fmt_int(x: int) -> str:
    return f"{x:,}"


class CostTracker:
    def __init__(self, pricing: dict | None = None):
        self.pricing = pricing or load_pricing()
        # agent -> {"model": str, "input": int, "cached": int, "output": int, "reasoning": int}
        self.text: dict[str, dict] = {}
        # image model -> count
        self.images: dict[str, int] = {}

    # ---- ingestion -------------------------------------------------------
    def add_text_usage(self, agent: str, model: str, input_t: int, output_t: int,
                       cached_t: int = 0, reasoning_t: int = 0) -> None:
        row = self.text.setdefault(
            agent or "unknown",
            {"model": model or "unknown", "input": 0, "cached": 0, "output": 0, "reasoning": 0},
        )
        if model:
            row["model"] = model
        row["input"] += int(input_t or 0)
        row["cached"] += int(cached_t or 0)
        row["output"] += int(output_t or 0)
        row["reasoning"] += int(reasoning_t or 0)

    def add_images(self, model: str, count: int = 1) -> None:
        self.images[model or "unknown"] = self.images.get(model or "unknown", 0) + int(count or 0)

    # ---- costing ---------------------------------------------------------
    def _text_cost(self, model: str, input_t: int, cached_t: int, output_t: int) -> float:
        r = _rate(self.pricing.get("text_per_1m_tokens", {}), model)
        billable_input = max(0, input_t - cached_t)
        return (
            billable_input / 1e6 * float(r.get("input", 0))
            + cached_t / 1e6 * float(r.get("cached_input", r.get("input", 0)))
            + output_t / 1e6 * float(r.get("output", 0))
        )

    def _image_cost(self, model: str, count: int) -> float:
        r = _rate(self.pricing.get("image_per_image", {}), model)
        return count * float(r.get("per_image", 0))

    def totals(self) -> dict:
        buckets = {"content": 0.0, "deploy": 0.0, "images": 0.0}
        tok = {"input": 0, "output": 0}
        for agent, row in self.text.items():
            cost = self._text_cost(row["model"], row["input"], row["cached"], row["output"])
            tok["input"] += row["input"]
            tok["output"] += row["output"]
            if agent in _DEPLOY_AGENTS:
                buckets["deploy"] += cost
            elif agent in _IMAGE_AGENTS:
                buckets["images"] += cost
            else:
                buckets["content"] += cost
        for model, count in self.images.items():
            buckets["images"] += self._image_cost(model, count)
        grand = sum(buckets.values())
        return {"buckets": buckets, "tokens": tok, "grand_total": grand}

    def has_data(self) -> bool:
        return bool(self.text or self.images)

    # ---- rendering -------------------------------------------------------
    def report(self) -> str:
        if not self.has_data():
            return ""
        lines = ["────────── Token & Cost Usage ──────────"]

        def agent_line(agent: str, row: dict) -> str:
            cost = self._text_cost(row["model"], row["input"], row["cached"], row["output"])
            return (
                f"  {agent} [{row['model']}]: "
                f"{_fmt_int(row['input'])} in"
                f"{f' ({_fmt_int(row['cached'])} cached)' if row['cached'] else ''} / "
                f"{_fmt_int(row['output'])} out → {_money(cost)}"
            )

        for title, members in (
            ("Content", _CONTENT_AGENTS),
            ("Deploy (translations + git)", _DEPLOY_AGENTS),
            ("Image agent (text)", _IMAGE_AGENTS),
        ):
            rows = {a: r for a, r in self.text.items() if a in members}
            if rows:
                lines.append(f"{title}:")
                for agent, row in rows.items():
                    lines.append(agent_line(agent, row))

        # any agent not in a known bucket
        other = {a: r for a, r in self.text.items()
                 if a not in _CONTENT_AGENTS | _DEPLOY_AGENTS | _IMAGE_AGENTS}
        if other:
            lines.append("Other:")
            for agent, row in other.items():
                lines.append(agent_line(agent, row))

        if self.images:
            lines.append("Images (generation):")
            for model, count in self.images.items():
                lines.append(f"  {model}: {count} image(s) → {_money(self._image_cost(model, count))}")

        t = self.totals()
        lines.append("─────────────────────────────────────────")
        lines.append(
            f"  Content {_money(t['buckets']['content'])} · "
            f"Deploy {_money(t['buckets']['deploy'])} · "
            f"Images {_money(t['buckets']['images'])}"
        )
        lines.append(
            f"  Tokens: {_fmt_int(t['tokens']['input'])} in / {_fmt_int(t['tokens']['output'])} out"
        )
        lines.append(f"  ESTIMATED TOTAL: {_money(t['grand_total'])}")
        if self.pricing.get("rates_are_examples"):
            lines.append("  ⚠ Using EXAMPLE rates — edit pricing.json with your real prices.")
        return "\n".join(lines)
