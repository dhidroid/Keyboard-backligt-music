import numpy as np

import kblight


def test_block_size_is_supported_by_coreaudio():
    assert 15 <= kblight.BLOCK <= 512


def test_analyzer_returns_zero_for_silence():
    analyzer = kblight.Analyzer()
    block = np.zeros(kblight.BLOCK)

    assert analyzer.update(block) == 0.0


def test_analyzer_detects_a_loud_transient_for_flashing():
    analyzer = kblight.Analyzer()
    quiet = np.zeros(kblight.BLOCK)
    loud = np.sin(np.linspace(0, 2 * np.pi * 8, kblight.BLOCK))

    analyzer.update(quiet)
    analyzer.update(loud)

    assert analyzer.level > 0.5
    assert analyzer.flash == 1.0


def test_analyzer_flash_decays_after_the_transient():
    analyzer = kblight.Analyzer()
    loud = np.sin(np.linspace(0, 2 * np.pi * 8, kblight.BLOCK))

    analyzer.update(loud)
    initial_flash = analyzer.flash
    analyzer.update(np.zeros(kblight.BLOCK))

    assert initial_flash == 1.0
    assert 0.0 < analyzer.flash < initial_flash
