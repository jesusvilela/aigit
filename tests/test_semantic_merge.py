"""Tests for semantic merge conflict detection."""
from aigit.core import (
    _body_text,
    _content_hash,
    _simhash,
    compute_semantic_conflicts,
    detect_duplicate_work,
)


def _c(sid, h, path="m.py", anchor="f"):
    return {sid: {"content_hash": h, "path": path, "anchor": anchor}}


def _real(sid, body, path="m.py", anchor="f", chunk_type="function"):
    """A manifest record with hashes/fingerprints computed from real text."""
    return {
        sid: {
            "semantic_id": sid,
            "path": path,
            "anchor": anchor,
            "chunk_type": chunk_type,
            "content_hash": _content_hash(body),
            "fingerprint": _simhash(body),
            "body_fingerprint": _simhash(_body_text(body)),
            "start_line": 1,
            "end_line": len(body.splitlines()),
        }
    }


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


# --------------------------------------------------------------------------- #
# duplicate work: same behaviour, different name (add/add is name-keyed and
# cannot see it -- two agents on one ticket rarely pick the same identifier).
# --------------------------------------------------------------------------- #
def _body(name):
    """A chunk body as the chunker really sees it: the ``def`` line -- and so
    the function name -- is part of the hashed text."""
    return (
        f"def {name}(model):\n"
        "    for provider in _PROVIDERS:\n"
        "        if model in provider['models']:\n"
        "            return provider['name']\n"
        "    return 'fallback'\n"
    )


BODY = _body("pick_provider")


def test_same_work_under_two_names_is_flagged():
    """The real CC1 case: two agents, one ticket, different identifiers.

    Scored on the whole chunk this pair reached only 0.84 and slipped under the
    gate; excluding the differing ``def`` line shows the bodies are identical."""
    ours = _real("s1", _body("pick_provider"), anchor="pick_provider")
    theirs = _real("s2", _body("choose_provider"), anchor="choose_provider")
    (c,) = compute_semantic_conflicts({}, ours, theirs)
    assert c["kind"] == "duplicate-work"
    assert c["anchor"] == "pick_provider"
    assert c["theirs_anchor"] == "choose_provider"
    assert c["similarity"] == 1.0


def test_verbatim_copy_under_a_different_name_is_flagged():
    ours = _real("s1", BODY, anchor="pick_provider")
    theirs = _real("s2", BODY, anchor="choose_provider")
    (c,) = detect_duplicate_work({}, ours, theirs)
    assert c["similarity"] == 1.0


def test_short_near_matches_are_not_accused_of_duplication():
    # one-liners carry too little SimHash signal to call duplicate work
    ours = _real("s1", "def a():\n    return 1\n", anchor="a")
    theirs = _real("s2", "def b():\n    return 2\n", anchor="b")
    assert detect_duplicate_work({}, ours, theirs) == []


def test_unrelated_additions_stay_clean():
    ours = _real("s1", BODY, anchor="pick_provider")
    theirs = _real(
        "s2",
        "def allow_request(bucket, cost=1):\n"
        "    bucket['tokens'] -= cost\n"
        "    return bucket['tokens'] >= 0\n",
        anchor="allow_request",
    )
    assert detect_duplicate_work({}, ours, theirs) == []


def test_cross_file_exact_copy_is_flagged_but_near_match_is_not():
    ours = _real("s1", BODY, path="a.py", anchor="pick_provider")
    exact = _real("s2", BODY, path="b.py", anchor="choose_provider")
    assert len(detect_duplicate_work({}, ours, exact)) == 1
    near = _real("s3", BODY.replace("'fallback'", "'default'"), path="b.py", anchor="choose")
    assert detect_duplicate_work({}, ours, near) == []


def test_pre_existing_chunk_is_not_duplicate_work():
    # both sides carry a chunk that already existed on base -> not new work
    base = _real("s1", BODY, anchor="pick_provider")
    theirs = _real("s2", BODY, anchor="choose_provider")
    assert detect_duplicate_work(base, base, theirs) == []


def test_each_chunk_is_paired_at_most_once():
    ours = {**_real("s1", BODY, anchor="pick_provider")}
    theirs = {
        **_real("s2", BODY, anchor="choose_provider"),
        **_real("s3", BODY, anchor="select_provider"),
    }
    dupes = detect_duplicate_work({}, ours, theirs)
    assert len(dupes) == 1


def test_duplicate_work_detection_can_be_disabled():
    ours = _real("s1", BODY, anchor="pick_provider")
    theirs = _real("s2", BODY, anchor="choose_provider")
    assert compute_semantic_conflicts({}, ours, theirs, include_duplicate_work=False) == []


def test_different_chunk_types_are_never_duplicates():
    ours = _real("s1", BODY, anchor="pick_provider", chunk_type="function")
    theirs = _real("s2", BODY, anchor="pick_provider", chunk_type="section")
    assert detect_duplicate_work({}, ours, theirs) == []


def test_one_line_bodies_are_never_accused_even_when_identical():
    """Guard the widened rule: an identical one-liner is too weak to accuse."""
    ours = _real("s1", "def a(x):\n    return x\n", path="a.py", anchor="a")
    theirs = _real("s2", "def b(x):\n    return x\n", path="b.py", anchor="b")
    assert detect_duplicate_work({}, ours, theirs) == []


def test_bodyless_chunks_are_not_treated_as_identical():
    """An empty body hashes to all zeros. Two chunks with nothing in them are
    an absence of evidence, not a match -- otherwise every stub in a codebase
    duplicates every other stub."""
    from aigit.core import _body_similarity

    ours = _real("s1", "def stub_a():\n    ...\n    ...\n", path="a.py", anchor="stub_a")
    theirs = _real("s2", "def stub_b():\n    ...\n    ...\n", path="b.py", anchor="stub_b")
    assert ours["s1"]["body_fingerprint"] == "0" * 16
    assert _body_similarity(ours["s1"], theirs["s2"]) < 1.0
    assert detect_duplicate_work({}, ours, theirs) == []


def test_chunks_without_body_fingerprints_fall_back_rather_than_match():
    """Not every parser produces a body: the TypeScript parser chunks
    declarations only. Those must compare on the whole chunk, not silently
    match each other."""
    from aigit.core import _body_similarity

    ours = _real("s1", BODY, anchor="pick_provider")
    theirs = _real("s2", _body("choose_provider"), anchor="choose_provider")
    del ours["s1"]["body_fingerprint"], theirs["s2"]["body_fingerprint"]
    assert 0.0 < _body_similarity(ours["s1"], theirs["s2"]) < 1.0
