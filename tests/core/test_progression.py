from uuid import uuid4

from lionag2.core import Progression


class TestProgression:
    def test_empty(self):
        p = Progression()
        assert len(p) == 0
        assert list(p) == []

    def test_append(self):
        p = Progression()
        u = uuid4()
        p.append(u)
        assert len(p) == 1
        assert u in p
        assert p[0] == u

    def test_append_allows_duplicates(self):
        p = Progression()
        u = uuid4()
        p.append(u)
        p.append(u)
        assert len(p) == 2
        assert u in p

    def test_include_idempotent(self):
        p = Progression()
        u = uuid4()
        assert p.include(u) is True
        assert p.include(u) is False
        assert len(p) == 1

    def test_remove(self):
        p = Progression()
        u1, u2 = uuid4(), uuid4()
        p.append(u1)
        p.append(u2)
        assert p.remove(u1) is True
        assert u1 not in p
        assert len(p) == 1

    def test_remove_missing(self):
        p = Progression()
        assert p.remove(uuid4()) is False

    def test_remove_many(self):
        p = Progression()
        uids = [uuid4() for _ in range(5)]
        for u in uids:
            p.append(u)
        removed = p.remove_many({uids[0], uids[2], uids[4]})
        assert removed == 3
        assert len(p) == 2
        assert list(p) == [uids[1], uids[3]]

    def test_clear(self):
        p = Progression()
        for _ in range(3):
            p.append(uuid4())
        p.clear()
        assert len(p) == 0

    def test_getitem_index(self):
        p = Progression()
        uids = [uuid4() for _ in range(3)]
        for u in uids:
            p.append(u)
        assert p[0] == uids[0]
        assert p[-1] == uids[2]

    def test_getitem_slice(self):
        p = Progression()
        uids = [uuid4() for _ in range(5)]
        for u in uids:
            p.append(u)
        assert p[1:3] == [uids[1], uids[2]]

    def test_name(self):
        p = Progression(name="bus")
        assert p.name == "bus"
        assert "bus" in repr(p)

    def test_iter(self):
        p = Progression()
        uids = [uuid4() for _ in range(3)]
        for u in uids:
            p.append(u)
        assert list(p) == uids

    def test_contains_o1(self):
        p = Progression()
        u = uuid4()
        p.append(u)
        assert u in p
        assert uuid4() not in p
