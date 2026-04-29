"""Cost estimation for Claude API document extraction."""

from .models import DocProfile, ChunkPlan

# Claude Sonnet 4.6 pricing (as of April 2026)
SONNET_INPUT_COST_PER_M = 3.00  # $3.00 per million input tokens
SONNET_OUTPUT_COST_PER_M = 15.00  # $15.00 per million output tokens


def estimate_total_cost(
    doc_profile: DocProfile,
    chunk_plans: list[ChunkPlan],
    estimated_output_tokens_per_chunk: int = 4000,
) -> dict:
    """Estimate total extraction cost for a document.

    Args:
        doc_profile: Document profile with page metrics
        chunk_plans: List of chunk plans
        estimated_output_tokens_per_chunk: Average output tokens per chunk

    Returns:
        {
            "input_tokens": int,
            "output_tokens": int,
            "input_cost": float,
            "output_cost": float,
            "total_cost": float,
            "cost_per_page": float,
        }
    """
    total_input_tokens = sum(cp.estimated_input_tokens for cp in chunk_plans)
    total_output_tokens = len(chunk_plans) * estimated_output_tokens_per_chunk

    input_cost = (total_input_tokens / 1_000_000) * SONNET_INPUT_COST_PER_M
    output_cost = (total_output_tokens / 1_000_000) * SONNET_OUTPUT_COST_PER_M
    total_cost = input_cost + output_cost

    cost_per_page = total_cost / doc_profile.total_pages if doc_profile.total_pages > 0 else 0.0

    return {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
        "cost_per_page": cost_per_page,
    }


def estimate_chunk_cost(chunk_plan: ChunkPlan, output_tokens: int = 4000) -> float:
    """Estimate cost for a single chunk."""
    input_cost = (chunk_plan.estimated_input_tokens / 1_000_000) * SONNET_INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * SONNET_OUTPUT_COST_PER_M
    return input_cost + output_cost


def format_cost(cost: float) -> str:
    """Format cost as USD string."""
    return f"${cost:.3f}"
