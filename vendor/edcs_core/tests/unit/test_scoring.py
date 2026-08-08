from edcs.document_scanner.mandatory import Checklist, MandatoryDoc
from edcs.document_scanner.scoring import DocState, compute_score


def _cl():
    return Checklist(docs=[
        MandatoryDoc("HLD", ["HLD"], 10), MandatoryDoc("LLD", ["LLD"], 10),
        MandatoryDoc("MOP", ["MOP"], 10), MandatoryDoc("ROLLBACK_PLAN", ["Rollback"], 10),
        MandatoryDoc("RELEASE_NOTES", ["Release Notes"], 6),
        MandatoryDoc("USER_GUIDE", ["User Guide"], 6),
    ])


def _all_ok(cl):
    return [DocState(d.key, d.weight, present=True) for d in cl.docs]


def test_perfect_score():
    cl = _cl()
    assert compute_score(_all_ok(cl), cl).score == 100


def test_folder_missing_is_zero():
    cl = _cl()
    r = compute_score([], cl, folder_missing=True)
    assert r.score == 0 and r.caps_applied


def test_missing_hld_caps_70():
    cl = _cl()
    states = _all_ok(cl)
    states[0].present = False        # HLD, weight 10
    r = compute_score(states, cl)
    assert r.score == 70


def test_blank_doc_caps_40():
    cl = _cl()
    states = _all_ok(cl)
    states[4].blank = True           # Release Notes blank
    r = compute_score(states, cl)
    assert r.score == 40


def test_missing_low_weight_caps_85():
    cl = _cl()
    states = _all_ok(cl)
    states[5].present = False        # User Guide, weight 6
    r = compute_score(states, cl)
    assert r.score <= 85


def test_naming_only_caps_95():
    cl = _cl()
    states = _all_ok(cl)
    states[0].named_ok = False
    r = compute_score(states, cl)
    assert r.score == 95
