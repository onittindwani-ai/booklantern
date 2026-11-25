import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_env  # noqa: E402

EXAMPLE = (ROOT / ".env.example").read_text()


def filled(**changes: str) -> str:
    """The example with a real session secret and the given values changed."""
    values = {"SESSION_SECRET": "test-only-" + "k3Jd8sLw0PqZx7Vn2Bm5Tc9Rf4Hy1Ga6", "DEMO_MODE": "false", "POSTGRES_PASSWORD": "abc123", **changes}
    out = []
    for line in EXAMPLE.splitlines():
        name = line.split("=", 1)[0]
        out.append(f"{name}={values[name]}" if name in values and "=" in line and not line.startswith("#") else line)
    return "\n".join(out)


def test_the_example_with_a_real_secret_is_fine():
    assert check_env.check(EXAMPLE, filled()) == []


def test_the_groups_are_named_by_comments_after_a_blank_line_only():
    groups = {g for g, n, _ in check_env.parse_example(EXAMPLE) if n == "DEFAULT_TIMEZONE"}
    assert len(groups) == 1 and next(iter(groups)).startswith("Company")  # the note above DEFAULT_TIMEZONE did not start a group


def test_changing_company_rules_or_budgets_is_not_flagged_as_a_half_filled_group():
    env = filled(COMPANY_NAME="Rivera Works", COMPANY_ADDRESS="12 Main Street, Springfield", DEFAULT_TIMEZONE="Europe/London", LLM_CALL_BUDGET="500", LLM_BUDGET_USD="20", OWNER_PASSWORD_HASH="x", REMINDER_MAX_COUNT="3")
    assert check_env.check(EXAMPLE, env) == []


def test_a_half_filled_adapter_group_is_still_flagged():
    problems = check_env.check(EXAMPLE, filled(QBO_CLIENT_ID="abc"))
    assert any("QuickBooks" in p and "QBO_CLIENT_SECRET" in p for p in problems)
    assert check_env.check(EXAMPLE, filled(STRIPE_SECRET_KEY="sk_test_abc")) == []  # a one name group needs nothing more
