from uuid import UUID, uuid4

import pytest

from lionag2.core.utils import IDUtils as iu


class TestGetId:
    def test_uuid_passthrough(self):
        u = uuid4()
        assert iu.get_id(u) == u

    def test_string_uuid(self):
        u = uuid4()
        assert iu.get_id(str(u)) == u

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            iu.get_id("not-a-uuid")

    def test_invalid_string_suppress(self):
        assert iu.get_id("not-a-uuid", suppress=True) is None

    def test_lion_id_attribute(self):
        u = uuid4()

        class Obj:
            lion_id = u

        assert iu.get_id(Obj()) == u

    def test_no_lion_id_raises(self):
        class Obj:
            pass

        with pytest.raises(TypeError):
            iu.get_id(Obj())

    def test_no_lion_id_suppress(self):
        class Obj:
            pass

        assert iu.get_id(Obj(), suppress=True) is None

    def test_does_not_fallback_to_id(self):
        class Obj:
            id = "call_abc123"

        with pytest.raises(TypeError):
            iu.get_id(Obj())

    def test_prefers_lion_id_over_id(self):
        u = uuid4()

        class Obj:
            lion_id = u
            id = "call_abc123"

        assert iu.get_id(Obj()) == u


class TestIsId:
    def test_uuid(self):
        assert iu.is_id(uuid4()) is True

    def test_uuid_string(self):
        assert iu.is_id(str(uuid4())) is True

    def test_not_uuid(self):
        assert iu.is_id("hello") is False
        assert iu.is_id(42) is False


class TestEnsureId:
    def test_stamps_lion_id(self):
        class Obj:
            pass

        o = Obj()
        uid = iu.ensure_id(o)
        assert isinstance(uid, UUID)
        assert o.lion_id == uid

    def test_idempotent(self):
        class Obj:
            pass

        o = Obj()
        uid1 = iu.ensure_id(o)
        uid2 = iu.ensure_id(o)
        assert uid1 == uid2

    def test_preserves_existing(self):
        u = uuid4()

        class Obj:
            lion_id = u

        assert iu.ensure_id(Obj()) == u


class TestTypeName:
    def test_type_name(self):
        class Foo:
            pass

        f = Foo()
        name = iu.type_name(f)
        assert "Foo" in name

    def test_type_name_from_class(self):
        class Bar:
            pass

        name = iu.type_name_from_class(Bar)
        assert "Bar" in name
