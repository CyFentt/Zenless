from hypothesis import given, settings
from hypothesis import strategies as st

from zenless.studio_mcp import validate_json_schema


@settings(max_examples=250)
@given(st.lists(st.integers(), max_size=20), st.integers(0, 10), st.integers(10, 20))
def test_array_bounds_hold_without_item_schema(values, lower, upper):
    schema = {'type': 'array', 'minItems': lower, 'maxItems': upper}
    assert bool(validate_json_schema(values, schema)) == (not lower <= len(values) <= upper)


@settings(max_examples=250)
@given(st.text(max_size=30), st.integers(0, 30))
def test_composition_keeps_sibling_constraints(value, minimum):
    schema = {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'minLength': minimum}
    assert bool(validate_json_schema(value, schema)) == (len(value) < minimum)


@settings(max_examples=250)
@given(st.one_of(st.integers(), st.text(), st.none(), st.booleans()))
def test_nullable_string_union(value):
    valid = value is None or isinstance(value, str)
    assert (not validate_json_schema(value, {'type': ['string', 'null']})) is valid
