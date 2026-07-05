import numpy as np

from birdframe.listener import Chunker


def test_chunker_emits_when_full():
    chunker = Chunker(chunk_samples=4, overlap_samples=1)
    assert chunker.push(np.array([1, 2], dtype=np.float32)) == []
    out = chunker.push(np.array([3, 4, 5], dtype=np.float32))
    assert len(out) == 1
    np.testing.assert_array_equal(out[0], [1, 2, 3, 4])


def test_chunker_retains_overlap_for_next_chunk():
    chunker = Chunker(chunk_samples=4, overlap_samples=1)
    chunker.push(np.arange(4, dtype=np.float32))          # emits [0,1,2,3], keeps [3]
    out = chunker.push(np.array([4, 5, 6], dtype=np.float32))  # [3,4,5,6]
    assert len(out) == 1
    np.testing.assert_array_equal(out[0], [3, 4, 5, 6])


def test_chunker_emits_multiple_when_backlogged():
    chunker = Chunker(chunk_samples=4, overlap_samples=0)
    out = chunker.push(np.arange(8, dtype=np.float32))
    assert len(out) == 2
    np.testing.assert_array_equal(out[0], [0, 1, 2, 3])
    np.testing.assert_array_equal(out[1], [4, 5, 6, 7])
