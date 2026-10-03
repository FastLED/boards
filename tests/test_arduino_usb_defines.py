from builders.extract_arduino import _collect_vid_pid_pairs
from builders.extract_boards import _arduino_primary_compile_identity, _arduino_vidpids


PICO_BUILD = {
    "usbvid": "-DUSBD_VID=0x2e8a",
    "usbpid": "-DUSBD_PID=0x000a",
}


def test_arduino_product_extractor_reads_usbd_compiler_defines() -> None:
    assert _collect_vid_pid_pairs({"build": PICO_BUILD}) == [("2e8a", "000a")]


def test_board_extractor_publishes_usbd_compiler_defines_as_primary() -> None:
    board = {"build": PICO_BUILD}
    assert _arduino_vidpids(board) == [["2e8a", "000a"]]
    assert _arduino_primary_compile_identity(board) == "2e8a:000a"


def test_standard_build_vid_pid_remain_preferred() -> None:
    board = {
        "build": {
            "vid": "0x1234",
            "pid": "0x5678",
            **PICO_BUILD,
        }
    }
    assert _collect_vid_pid_pairs(board) == [("1234", "5678")]
    assert _arduino_vidpids(board) == [["1234", "5678"]]
    assert _arduino_primary_compile_identity(board) == "1234:5678"


def test_malformed_or_partial_usbd_defines_fail_closed() -> None:
    assert _collect_vid_pid_pairs({"build": {"usbvid": "-DUSBD_VID=not-hex"}}) == []
    assert _arduino_primary_compile_identity({"build": {"usbpid": "-DUSBD_PID=0x000a"}}) is None
