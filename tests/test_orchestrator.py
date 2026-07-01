from myruflo.swarm.orchestrator import FULL_PIPELINE, choose_pipeline


def test_force_no_swarm_always_generalist():
    assert choose_pipeline("implement a full feature module", force_swarm=False) == ["generalist"]


def test_force_swarm_always_full_pipeline():
    assert choose_pipeline("say hi", force_swarm=True) == FULL_PIPELINE


def test_bug_fix_routes_to_research_code_test():
    assert choose_pipeline("fix the crash in the login handler") == ["researcher", "coder", "tester"]


def test_short_simple_task_routes_to_generalist():
    assert choose_pipeline("what time zone is UTC") == ["generalist"]


def test_security_task_routes_to_research_and_review():
    assert choose_pipeline("audit this module for security vulnerabilities") == ["researcher", "reviewer"]


def test_long_task_without_keywords_falls_back_to_full_pipeline():
    long_task = " ".join(["word"] * 41)
    assert choose_pipeline(long_task) == FULL_PIPELINE
