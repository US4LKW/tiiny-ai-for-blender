"""Independent semantic fixtures for conservative segmentation-mask cleanup.

The expected masks describe pixels to preserve or clear before any crop/resize.
They intentionally do not specify an implementation or test every ambiguous
semi-transparent structure. An alpha mask alone cannot identify all shadows.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw


@dataclass
class MaskFixture:
    name: str
    rgba: np.ndarray
    preserve_alpha: np.ndarray
    clear_alpha: np.ndarray
    note: str


def image_from_alpha(alpha):
    """Nonuniform RGB makes accidental foreground recoloring detectable."""
    yy, xx = np.indices(alpha.shape)
    rgb = np.stack(((xx * 3 + yy) % 256,
                    (xx + yy * 5) % 256,
                    (xx * 7 + yy * 11) % 256), axis=-1).astype(np.uint8)
    return np.dstack((rgb, np.asarray(alpha, dtype=np.uint8)))


def fixtures():
    size = (512, 512)
    blank = np.zeros(size, dtype=np.uint8)
    none = np.zeros(size, dtype=bool)

    yield MaskFixture('empty', image_from_alpha(blank), np.ones(size, dtype=bool),
                      none.copy(), 'No fabricated opaque pixels in an empty mask.')
    full = np.full(size, 255, dtype=np.uint8)
    yield MaskFixture('opaque', image_from_alpha(full), np.ones(size, dtype=bool),
                      none.copy(), 'No segmentation: fully opaque input is unchanged.')

    low = Image.new('L', size, 0)
    ImageDraw.Draw(low).ellipse((100, 100, 411, 411), fill=38)
    low = np.asarray(low)
    yield MaskFixture('fully_translucent', image_from_alpha(low), np.ones(size, dtype=bool),
                      none.copy(), 'No confident foreground: do not erase the whole object.')

    alpha_image = Image.new('L', size, 0)
    draw = ImageDraw.Draw(alpha_image)
    draw.rectangle((120, 100, 370, 300), fill=255)
    # An opaque one-pixel filament with a soft one-pixel fringe on each side.
    draw.line((250, 100, 250, 20), fill=255, width=1)
    draw.line((249, 100, 249, 20), fill=35, width=1)
    draw.line((251, 100, 251, 20), fill=35, width=1)
    # A detached solid piece can legitimately be part of the selected subject.
    draw.rectangle((420, 170, 440, 190), fill=255)
    # The original dark alpha shadow is connected directly to the main object.
    draw.rectangle((180, 301, 350, 375), fill=50)
    alpha = np.asarray(alpha_image)
    preserve = alpha >= 128
    preserve[20:101, 249:252] = True
    clear = none.copy()
    clear[340:375, 200:330] = True
    yield MaskFixture('thin_detail_and_shadow', image_from_alpha(alpha), preserve, clear,
                      'Preserve opaque details and soft fringe; clear distant weak shadow.')

    holes = Image.new('L', size, 0)
    draw = ImageDraw.Draw(holes)
    draw.ellipse((80, 80, 432, 432), fill=255)
    draw.ellipse((170, 170, 342, 342), fill=0)
    draw.line((90, 250, 180, 250), fill=0, width=1)
    holes = np.asarray(holes)
    yield MaskFixture('real_holes', image_from_alpha(holes), np.ones(size, dtype=bool),
                      none.copy(), 'No closing/filling of subject apertures or thin cutouts.')

    multiple = Image.new('L', size, 0)
    draw = ImageDraw.Draw(multiple)
    draw.rectangle((25, 75, 225, 425), fill=255)
    draw.ellipse((350, 210, 430, 290), fill=255)
    draw.line((290, 30, 290, 180), fill=255, width=1)
    multiple = np.asarray(multiple)
    yield MaskFixture('multiple_foreground_parts', image_from_alpha(multiple),
                      np.ones(size, dtype=bool), none.copy(),
                      'Do not apply a largest-connected-component filter by default.')

    weak_hair = Image.new('L', size, 0)
    draw = ImageDraw.Draw(weak_hair)
    draw.rectangle((120, 170, 360, 390), fill=255)
    draw.line((210, 170, 210, 40), fill=35, width=1)
    draw.line((260, 170, 300, 60), fill=20, width=1)
    draw.rectangle((180, 391, 350, 470), fill=50)
    weak_hair = np.asarray(weak_hair)
    preserve = weak_hair >= 64
    preserve[:170, :] |= weak_hair[:170, :] > 0
    clear = none.copy()
    clear[430:465, 210:320] = True
    yield MaskFixture('connected_weak_hair', image_from_alpha(weak_hair), preserve, clear,
                      'Connected fine low-alpha strands are useful foreground, not broad shadow.')

    uncertain = Image.new('L', size, 0)
    draw = ImageDraw.Draw(uncertain)
    draw.ellipse((120, 100, 390, 400), fill=150)
    draw.rectangle((180, 401, 350, 475), fill=40)
    uncertain = np.asarray(uncertain)
    yield MaskFixture('no_confident_foreground', image_from_alpha(uncertain),
                      np.ones(size, dtype=bool), none.copy(),
                      'An uncertain whole-object mask must not be guessed into a new silhouette.')


def evaluate(fixture, output_rgba):
    """Return behavioral measurements; threshold-free checks remain explicit."""
    source = fixture.rgba
    output = np.asarray(output_rgba)
    assert output.shape == source.shape, 'Evaluate cleanup before crop/resize.'
    assert output.dtype == np.uint8
    retained = output[:, :, 3] > 0
    return {
        'name': fixture.name,
        'alpha_changed_in_preserve_region': int(np.count_nonzero(
            output[:, :, 3][fixture.preserve_alpha] != source[:, :, 3][fixture.preserve_alpha])),
        'nonzero_alpha_in_clear_region': int(np.count_nonzero(output[:, :, 3][fixture.clear_alpha])),
        'pixels_with_increased_alpha': int(np.count_nonzero(output[:, :, 3] > source[:, :, 3])),
        'recolored_retained_pixels': int(np.count_nonzero(np.any(
            output[:, :, :3][retained] != source[:, :, :3][retained], axis=1))),
        'retained_nonzero_pixels': int(np.count_nonzero(retained)),
    }
