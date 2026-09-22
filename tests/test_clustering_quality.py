from trendradar.cluster import same_event_score


def test_same_event_can_match_on_body_when_titles_differ():
    a_title = "Acme launches enterprise agent platform"
    b_title = "Acme says new software will automate IT operations"
    a_body = "Acme enterprise customers deploy the agent platform for IT operations and workflow automation."
    b_body = "The company said enterprise customers use the software for IT operations, workflow automation and support."
    assert same_event_score(a_title,a_body,b_title,b_body) >= 0.40


def test_broad_industry_overlap_does_not_collapse_unrelated_events():
    a_title = "Chipmaker opens new Arizona factory"
    b_title = "Cloud company signs renewable energy contract"
    shared = "AI infrastructure enterprise customers revenue growth market investment"
    assert same_event_score(a_title,shared,b_title,shared) < 0.40
