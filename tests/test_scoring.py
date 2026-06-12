from app.engine.scoring import criteria_score


def test_qualified_when_all_thresholds_met():
    score, qualified, checks = criteria_score(10.0, 4.0, 25.0, "earnings")
    assert qualified
    assert score >= 80
    assert all(checks[k]["ok"] for k in checks)


def test_not_qualified_low_gap():
    score, qualified, _ = criteria_score(2.0, 5.0, 50.0, "mover")
    assert not qualified
    assert score < 80
