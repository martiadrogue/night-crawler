from night_crawler.domain.rules.llm_rate_limits import (
    LlmBudget,
    resolve_llm_rate_limit_targets,
)

BUDGET = LlmBudget(
    requests_per_minute=10, requests_per_day=500, tokens_per_minute=250_000
)


def test_each_budget_gets_its_own_key_per_model():
    targets = resolve_llm_rate_limit_targets("gemini-2.5-flash", BUDGET)

    assert "llm:gemini-2.5-flash" == targets.key
    assert ("llm:gemini-2.5-flash:minute", "10/minute") == (
        targets.minute.key,
        targets.minute.rule.rate_limit_string,
    )
    assert ("llm:gemini-2.5-flash:day", "500/day") == (
        targets.day.key,
        targets.day.rule.rate_limit_string,
    )
    assert ("llm:gemini-2.5-flash:tokens", "250000/minute") == (
        targets.tokens.key,
        targets.tokens.rule.rate_limit_string,
    )


def test_only_the_minute_key_carries_a_penalty():
    targets = resolve_llm_rate_limit_targets("gemini-2.5-flash", BUDGET)

    assert 0 < targets.minute.rule.penalty_step_seconds
    assert 0 < targets.minute.rule.max_penalty_seconds
    assert 0 == targets.day.rule.max_penalty_seconds
    assert 0 == targets.tokens.rule.max_penalty_seconds
