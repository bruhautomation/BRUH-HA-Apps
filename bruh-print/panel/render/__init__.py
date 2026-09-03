"""Label artwork: the document model, the fonts, the codes, and one renderer.

`image.render()` is the only route from a label to dots, and `image.
raster_lines()` the only route from dots to the printer's bytes. The panel's
preview and the print job are the same call with different endings, which is
what makes the preview worth looking at.
"""
from . import barcode, fonts, image, label  # noqa: F401

__all__ = ["barcode", "fonts", "image", "label"]
