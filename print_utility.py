#!/usr/bin/env python3
"""
PrintUtility

Usage:
    from print_utility import PrintUtility
    pu = PrintUtility()
    # on start-up
    pu.print_test()
    ...
    # for each user
    pu.print_header()
    pu.print_results(results)
    pu.print_footer()
"""

from datetime import datetime

from escpos.printer import Usb

VENDOR_ID = 0x04B8
PRODUCT_ID = 0x0202
IN_EP = 0x82
OUT_EP = 0x01

W = 42  # character width of receipt

DISCLAIMER = (
    "This is for informational purposes only and "
    "is not a substitute for professional medical advice, "
    "diagnosis, or treatment."
)


def _divider(char="-"):
    return char * W + "\n"


def _center(text):
    return text.center(W) + "\n"


def _wrap(text, width=W):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines


class PrintUtility:
    disclaimer = DISCLAIMER

    def __init__(self):
        try:
            self._p = Usb(VENDOR_ID, PRODUCT_ID, in_ep=IN_EP, out_ep=OUT_EP)
            self._p._raw(b"\x1b\x40")  # ESC @ — reset printer to defaults
        except Exception as e:
            raise RuntimeError(f"Could not open printer — {e}") from e

    # check the printer is working, should run at startup of main
    def print_test(self):
        """Print a short self-test page."""
        p = self._p
        p.set(align="center")
        p.text(_divider("-"))
        p.text(_center("HEARTPOD PRINTER TEST"))
        p.text(_divider("-"))
        p.set(align="left")
        p.text("Printer is working correctly.\n")
        p.text(f"  Width : {W} chars\n")
        p.text(f"  Time  : {datetime.now().strftime('%d %b %Y  %H:%M:%S')}\n")
        p.text(_divider())
        p.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ\n")
        p.text("abcdefghijklmnopqrstuvwxyz\n")
        p.text("0123456789 !@#$%^&*()-+=\n")
        p.text(_divider("-"))
        p.cut()

    # prints a string...
    def print_string(self, text):
        p = self._p
        p.set(align="left")
        p.text(text + "\n")

    # just prints the name and the date / time
    def print_header(self):
        p = self._p
        now = datetime.now()
        p.set(align="center", bold=True)
        p.text("HeartPod\n")
        p.set(align="center", bold=False)
        p.text(now.strftime("%-d %B %Y") + "\n")
        p.text(now.strftime("%H:%M:%S") + "\n")
        p.set(align="left")
        p.text("\n")
        p.text(_divider("-"))

    # prints the results, needs a dict, e.g.
    # print_results(
    #     {
    #         "spo2": 98,
    #         "heart_rate": 72,
    #         "weight": 70.5,
    #         "height": 1.75,
    #         "systolic": 120,
    #         "diastolic": 80,
    #     }
    # )

    def print_results(self, results):
        p = self._p

        def row(label, value):
            gap = W - len(label) - len(value)
            p.text(label + " " * max(gap, 1) + value + "\n")

        p.text("\n")

        p.set(align="center", bold=True)
        p.text("Measurements\n")

        p.set(align="left", bold=False)

        row("SpO2", f"{results['spo2']}%")
        row("Heart Rate", f"{results['heart_rate']} bpm")
        row("Weight", f"{results['weight']} kg")
        row("Height", f"{results['height']} m")
        row("Blood Pressure", f"{results['systolic']}/{results['diastolic']} mmHg")

        p.text("\n")

    # prints disclaimer and closing message
    def print_footer(self, disclaimer=None):
        if disclaimer is None:
            disclaimer = self.disclaimer
        p = self._p
        p.set(align="left")
        p.text(_divider("-"))
        p.set(align="center", bold=True)
        p.text("\n")
        p.text("Disclaimer\n")
        p.set(bold=False)
        for line in _wrap(disclaimer):
            p.text(line + "\n")
        p.text("\n")
        p.set(align="left")
        p.text(_divider("-"))
        p.set(align="center")
        p.text("\n")
        p.text("Thank you for using HeartPod.\n")
        p.text("\n")
        p.cut()


if __name__ == "__main__":
    pu = PrintUtility()

    pu.print_test()

    # pu.print_header()
    # pu.print_results(
    #     {
    #         "spo2": 98,
    #         "heart_rate": 72,
    #         "weight": 70.5,
    #         "height": 1.75,
    #         "systolic": 120,
    #         "diastolic": 80,
    #     }
    # )
    # pu.print_footer()
