"""Tests for semantic merge conflict detection."""
from aigit.core import compute_semantic_conflicts


def _c(sid, h, path="m.py", anchor="f"):
    return {sid: {"content_hash": h, "path": path, "anchor": anchor}}


def _kinds(conflicts):
    return {c["semantic_id"]: c["kind"] for c in conflicts}


def test_modify_modify_is_detected():
    base = _c("s1", "h0")
    ours = _c("s1", "hA")
    theirs = _c("s1", "hB")
    assert _kinds(compute_semantic_conflicts(base, ours, theirs)) == {"s1": "modify/modify"}


def test_add_add_divergent_is_detected():
    # absent in base, created differently on both sides
    base: dict = {}
    ours = _c("s1", "hA")
    theirs = _c("s1", "hB")
    assert _kinds(compute_semantic_conflicts(base, ours, theirs)) == {"s1": "add/add"}


def test_add_add_identical_is_clean():
    base: dict = {}
    ours = _c("s1", "hSAME")
    theirs = _c("s1", "hSAME")
    assert compute_semantic_conflicts(base, ours, theirs) == []


def test_modify_delete_is_detected():
    base = _c("s1", "h0")
    ours = _c("s1", "hA")  # edited on ours
    theirs: dict = {}       # deleted on theirs
    assert _kinds(compute_semantic_conflicts(base, ours, theirs)) == {"s1": "modify/delete"}


def test_delete_modify_is_detected():
    base = _c("s1", "h0")
    ours: dict = {}          # deleted on ours
    theirs = _c("s1", "hB")  # edited on theirs
    assert _kinds(compute_semantic_conflicts(base, ours, theirs)) == {"s1": "delete/modify"}


def test_one_sided_changes_are_clean():
    base = _c("s1", "h0")
    ours = _c("s1", "hA")       # only ours edits -> clean
    theirs = _c("s1", "h0")     # theirs unchanged
    assert compute_semantic_conflicts(base, ours, theirs) == []
    # clean add on a single side
    assert compute_semantic_conflicts({}, _c("s2", "hX"), {}) == []
    # both delete -> clean
    assert compute_semantic_conflicts(_c("s3", "h0"), {}, {}) == []


def test_conflict_record_carries_metadata():
    base: dict = {}
    ours = _c("s1", "hA", path="aigit/handlers.py", anchor="handler")
    theirs = _c("s1", "hB", path="aigit/handlers.py", anchor="handler")
    (c,) = compute_semantic_conflicts(base, ours, theirs)
    assert c["path"] == "aigit/handlers.py"
    assert c["anchor"] == "handler"
    assert c["ours_hash"] == "hA" and c["theirs_hash"] == "hB" and c["base_hash"] is None
