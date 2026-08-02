"""Recovery transforms: rebuild a readable image from text that defeats a
plain OCR pass.

Two attacks in the injection-fixtures corpus beat straight tesseract while
leaving the payload fully present in the pixels:

- Text one shade off its background ("white-on-white"). tesseract often does
  read it, but misreads enough vowels that the pattern engine misses. The
  text differs from a median-filtered copy of the image by exactly its
  contrast delta, so subtracting the two and amplifying what's left rebuilds
  a crisp black-on-white rendering of only the near-background detail.
- Text rotated well off-axis. tesseract tolerates a few degrees of skew and
  nothing more. The angle is recoverable without OCR: upright-ish text
  produces strong horizontal banding in an edge map, so sweeping candidate
  angles and scoring row-projection variance finds the angle at which the
  banding lines up, and one extra OCR pass on the counter-rotated image
  reads the payload.

Both transforms are pure Pillow and cheap relative to an OCR pass. The
scanner runs them only when the normal passes found no injection text, and
only inside the per-image time budget.
"""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageChops, ImageFilter

# Residual pass: |gray - median| isolates detail thinner than the median
# window (text strokes) regardless of how little contrast it has against the
# background. The gain then stretches a 1-shade difference to full black.
RESIDUAL_MEDIAN = 5
RESIDUAL_GAIN = 64

# Skew sweep: the projection profile is scored on a small thumbnail so the
# sweep costs milliseconds, not another OCR pass per angle.
SKEW_THUMBNAIL = 360
SKEW_MAX_DEGREES = 60
SKEW_STEP_DEGREES = 3
SKEW_MIN_DEGREES = 9  # inside this, tesseract reads the text unrotated anyway
# Acceptance is judged inside the off-axis family only. Every candidate angle
# pays the same interpolation-and-expand tax in _projection_variance, while
# angle 0 would pay none of it, so a comparison against the unrotated score
# structurally suppresses real peaks (a 20-megapixel screenshot's upright
# variance dwarfs every rotated score even when a rotated payload is there).
# A real rotated payload is a sharp, one-sided spike: far above the sweep's
# median, and far above its own mirror angle. Upright text produces a profile
# that decays symmetrically toward both ends of the sweep, which the mirror
# test rejects.
SKEW_MIN_SCORE = 1.0  # absolute floor; a blank or featureless image scores ~0
SKEW_MIN_PEAK_OVER_MEDIAN = 4.0
SKEW_MIN_PEAK_OVER_MIRROR = 3.0


def residual_text(gray: Image.Image) -> Image.Image:
    """A black-on-white rendering of detail that sits near its background.

    Median-filter the image (which erases strokes thinner than the window
    but keeps every background), subtract, and amplify. Text at any contrast
    above zero comes back at full contrast; flat areas come back white.
    """
    median = gray.filter(ImageFilter.MedianFilter(RESIDUAL_MEDIAN))
    diff = ImageChops.difference(gray, median)
    return diff.point(lambda v: max(0, 255 - v * RESIDUAL_GAIN))


def _projection_variance(edges: Image.Image, angle: int) -> float:
    rotated = edges.rotate(angle, expand=True, resample=Image.BILINEAR, fillcolor=0)
    height = rotated.height
    rows = rotated.resize((1, height), Image.BOX).tobytes()
    mean = sum(rows) / height
    return sum((v - mean) ** 2 for v in rows) / height


def detect_skew(gray: Image.Image) -> Optional[int]:
    """The angle (degrees) at which off-axis text in `gray` reads upright,
    or None when nothing looks rotated.

    Upright text stripes an edge map horizontally: rows through the ink are
    dense, rows between lines are empty, so the variance of the per-row mean
    peaks when the rotation angle matches the text. A flat or symmetric
    profile across the sweep means no rotated text worth an extra OCR pass.
    """
    thumb = gray.copy()
    thumb.thumbnail((SKEW_THUMBNAIL, SKEW_THUMBNAIL), Image.BILINEAR)
    edges = thumb.filter(ImageFilter.FIND_EDGES)

    scores = {}
    for angle in range(-SKEW_MAX_DEGREES, SKEW_MAX_DEGREES + 1, SKEW_STEP_DEGREES):
        if abs(angle) < SKEW_MIN_DEGREES:
            continue
        scores[angle] = _projection_variance(edges, angle)
    best_angle = max(scores, key=scores.get)
    best = scores[best_angle]
    median = sorted(scores.values())[len(scores) // 2]
    mirror = scores.get(-best_angle, 0.0)
    if best < SKEW_MIN_SCORE:
        return None
    if best < median * SKEW_MIN_PEAK_OVER_MEDIAN:
        return None
    if best < mirror * SKEW_MIN_PEAK_OVER_MIRROR:
        return None
    return best_angle


def deskewed(gray: Image.Image, angle: int) -> Image.Image:
    """`gray` counter-rotated so text detected at `angle` reads upright."""
    return gray.rotate(angle, expand=True, resample=Image.BICUBIC, fillcolor=255)
