"""Everything that knows a DYMO LabelWriter's wire shape lives here.

Three files, one job each: `protocol` builds bytes, `printers` says what a
given model can do, `usb_link` gets the bytes there. Nothing above this
package constructs an escape sequence or opens a device, so a new model or a
new transport is one file's problem.
"""
from . import printers, protocol, usb_link  # noqa: F401

__all__ = ["printers", "protocol", "usb_link"]
