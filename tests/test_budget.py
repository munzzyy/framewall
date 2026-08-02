"""The OCR fan-out bounds: the per-image time budget, the region cap, and
region merging. Every OCR'd region is its own tesseract subprocess, so
without these bounds one busy or crafted image could demand hundreds of
subprocesses and stall a synchronous caller (the Claude Code hook) for
hours. The other half of the contract is loudness: anything the bounds cut
short must surface as a note, never read as a completed clean scan."""

from __future__ import annotations

import time

from framewall import ocr as ocr_mod
from framewall.checks import injection_text
from framewall.finding import Region
from framewall.scanner import scan_image
from tests import _images


# --- ScanBudget ----------------------------------------------------------------


def test_unlimited_budget_never_exhausts():
    budget = ocr_mod.ScanBudget(None)
    assert budget.remaining() is None
    assert not budget.exhausted()
    assert budget.clamp(20) == 20


def test_budget_clamps_a_pass_timeout_to_what_is_left():
    budget = ocr_mod.ScanBudget(5)
    assert budget.clamp(20) <= 5
    assert budget.clamp(20) > 0


def test_budget_exhausts_after_its_deadline():
    budget = ocr_mod.ScanBudget(0.01)
    time.sleep(0.02)
    assert budget.exhausted()
    # Even exhausted, clamp returns a small positive value rather than a
    # zero/negative timeout that would make subprocess.run throw.
    assert budget.clamp(20) > 0


def test_budget_notes_deduplicate():
    budget = ocr_mod.ScanBudget(1)
    budget.note("same")
    budget.note("same")
    assert budget.notes == ["same"]


# --- region cap + merging ------------------------------------------------------


def _region(left, top, width=20, height=10):
    return Region(left, top, width, height)


def test_region_fanout_is_capped_and_noted():
    regions = [_region(x * 100, 0) for x in range(injection_text.MAX_OCR_REGIONS * 3)]
    budget = ocr_mod.ScanBudget(None)
    boxes = injection_text._bounded_boxes(regions, None, budget)
    assert len(boxes) == injection_text.MAX_OCR_REGIONS
    assert any("partial" in n for n in budget.notes)


def test_uncapped_fanout_produces_no_note():
    budget = ocr_mod.ScanBudget(None)
    injection_text._bounded_boxes([_region(0, 0), _region(500, 0)], None, budget)
    assert budget.notes == []


def test_biggest_regions_survive_the_cap():
    """The largest hidden-text region is the most likely payload; the cap
    must drop the smallest candidates, not the first-listed ones."""
    small = [_region(x * 100, 200, 10, 5) for x in range(injection_text.MAX_OCR_REGIONS)]
    big = _region(0, 0, 400, 60)
    budget = ocr_mod.ScanBudget(None)
    boxes = injection_text._bounded_boxes(small + [big], None, budget)
    assert boxes[0] == (0, 0, 400, 60)


def test_adjacent_regions_merge_into_one_box():
    # Two halves of one paragraph, split by the block grid: closer than
    # REGION_MERGE_GAP, so one crop (one subprocess), not two.
    merged = injection_text._merge_boxes([(0, 0, 100, 20), (104, 0, 200, 20)])
    assert merged == [(0, 0, 200, 20)]


def test_distant_regions_stay_separate():
    merged = injection_text._merge_boxes([(0, 0, 100, 20), (400, 300, 500, 320)])
    assert len(merged) == 2


def test_merge_reaches_a_fixpoint_through_chains():
    # a-b merge first, and the union then also overlaps c: one box out.
    merged = injection_text._merge_boxes(
        [(0, 0, 100, 20), (105, 0, 205, 20), (210, 0, 310, 20)]
    )
    assert merged == [(0, 0, 310, 20)]


# --- scan-level loudness -------------------------------------------------------


def test_exhausted_budget_surfaces_as_a_note_on_the_result(tmp_path, monkeypatch):
    """A scan whose time budget ran out must say so on the result. OCR is
    faked so this runs everywhere and takes no real time."""
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda lang=None: True)
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")

    def slow_ocr(image, timeout=ocr_mod.DEFAULT_TIMEOUT, lang=None):
        time.sleep(0.05)
        return [], []

    monkeypatch.setattr(ocr_mod, "ocr_image", slow_ocr)
    p = tmp_path / "busy.png"
    _images.low_contrast_paragraph().save(p)
    result = scan_image(p, max_seconds=0.01)
    assert result.notes, "a scan cut short by its budget must carry a note"
    assert any("partial" in n for n in result.notes)


def test_normal_scan_carries_no_notes(tmp_path):
    p = tmp_path / "clean.png"
    _images.clean_screenshot().save(p)
    result = scan_image(p, use_ocr=False)
    assert result.notes == []
